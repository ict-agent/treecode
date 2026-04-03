# Agent Loop 引擎

Agent Loop 是 OpenHarness 的心脏——它实现了「用户输入 → LLM 思考 → 工具调用 → 结果回传 → 继续思考」的核心循环。

> 对应源码：`src/openharness/engine/`

---

## 模块组成

| 文件 | 职责 |
|------|------|
| `query.py` | 核心循环 `run_query()` + 工具执行 `_execute_tool_call()` |
| `query_engine.py` | 高层封装 `QueryEngine` 类，管理会话历史和 usage |
| `messages.py` | `ConversationMessage`, `TextBlock`, `ToolUseBlock`, `ToolResultBlock` |
| `stream_events.py` | 流式事件：`AssistantTextDelta`, `ToolExecutionStarted/Completed` |
| `cost_tracker.py` | Token 用量累积追踪 |

---

## 核心循环：`run_query()`

> 源码：[`engine/query.py`](../src/openharness/engine/query.py)

```python
async def run_query(
    context: QueryContext,
    messages: list[ConversationMessage],
) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]:
```

### 循环流程

```
for turn in range(max_turns):    # 默认最多 8 轮
    │
    ├── 1. 调用 API 流式请求
    │     api_client.stream_message(ApiMessageRequest(...))
    │     ├── yield ApiTextDeltaEvent → 转为 AssistantTextDelta 事件
    │     └── yield ApiMessageCompleteEvent → 获取 final_message
    │
    ├── 2. 将 assistant 消息追加到 messages
    │     messages.append(final_message)
    │     yield AssistantTurnComplete(message, usage)
    │
    ├── 3. 检查是否有工具调用
    │     if not final_message.tool_uses:
    │         return  ← 模型决定停止，退出循环
    │
    ├── 4. 执行工具调用
    │     ├── 单工具：顺序执行
    │     │     result = await _execute_tool_call(...)
    │     │
    │     └── 多工具：并发执行
    │           results = await asyncio.gather(
    │               *[_execute_tool_call(...) for tc in tool_calls]
    │           )
    │
    └── 5. 将工具结果追加到 messages，继续循环
          messages.append(ConversationMessage(role="user", content=tool_results))
```

### 关键设计点

**1. 单/并行工具执行自动切换**

```python
if len(tool_calls) == 1:
    # 单工具：顺序执行，事件实时流出
    result = await _execute_tool_call(context, tc.name, tc.id, tc.input)
else:
    # 多工具：asyncio.gather 并发执行
    results = await asyncio.gather(*[_run(tc) for tc in tool_calls])
```

当模型返回单个 `tool_use` 时顺序执行，多个时自动并发——这是 Agent Loop 的性能关键。

**2. max_turns 保护**

循环有 `max_turns`（默认 8）限制。超过后抛出 `RuntimeError`，防止无限循环。

**3. AsyncIterator 流式输出**

`run_query()` 返回 `AsyncIterator`，调用方可以逐步接收事件用于 UI 渲染：

```python
async for event, usage in run_query(context, messages):
    if isinstance(event, AssistantTextDelta):
        print(event.text, end="")  # 实时打印文本
    elif isinstance(event, ToolExecutionStarted):
        print(f"⚙ Running {event.tool_name}...")
```

---

## 工具执行：`_execute_tool_call()`

> 源码：[`engine/query.py`](../src/openharness/engine/query.py) 第 124-211 行

这是每次工具调用的完整执行流程：

```
_execute_tool_call(context, tool_name, tool_use_id, tool_input)
│
├── 1. PreToolUse Hook 检查
│     hook_executor.execute(HookEvent.PRE_TOOL_USE, payload)
│     └── 如果 blocked → 返回错误 ToolResultBlock
│
├── 2. 工具查找
│     tool = tool_registry.get(tool_name)
│     └── 未知工具 → 返回 "Unknown tool: xxx" 错误
│
├── 3. 输入验证 (Pydantic)
│     parsed_input = tool.input_model.model_validate(tool_input)
│     └── 验证失败 → 返回 "Invalid input" 错误
│
├── 4. 权限检查
│     decision = permission_checker.evaluate(
│         tool_name,
│         is_read_only=tool.is_read_only(parsed_input),
│         file_path=..., command=...
│     )
│     ├── denied & requires_confirmation → 弹出用户确认
│     └── denied & 不可确认 → 返回 "Permission denied" 错误
│
├── 5. 执行工具
│     result = await tool.execute(parsed_input, ToolExecutionContext(...))
│
└── 6. PostToolUse Hook 通知
      hook_executor.execute(HookEvent.POST_TOOL_USE, {
          tool_name, tool_input, tool_output, tool_is_error, ...
      })
```

### 权限检查细节

工具执行前会从 `tool_input` 中提取 `file_path` 和 `command` 字段，传递给 `PermissionChecker`：

```python
_file_path = str(tool_input.get("file_path", "")) or None
_command = str(tool_input.get("command", "")) or None
decision = context.permission_checker.evaluate(
    tool_name,
    is_read_only=tool.is_read_only(parsed_input),
    file_path=_file_path,
    command=_command,
)
```

---

## QueryEngine 封装

> 源码：[`engine/query_engine.py`](../src/openharness/engine/query_engine.py)

`QueryEngine` 是对 `run_query()` 的有状态封装，管理完整的会话生命周期：

```python
class QueryEngine:
    """Owns conversation history and the tool-aware model loop."""

    def __init__(self, *, api_client, tool_registry, permission_checker, cwd, model,
                 system_prompt, max_tokens=4096, permission_prompt=None,
                 ask_user_prompt=None, hook_executor=None, tool_metadata=None):
        self._messages: list[ConversationMessage] = []
        self._cost_tracker = CostTracker()
        # ... 其他字段

    async def submit_message(self, prompt: str) -> AsyncIterator[StreamEvent]:
        """追加用户消息并执行 query 循环。"""
        self._messages.append(ConversationMessage.from_user_text(prompt))
        context = QueryContext(...)  # 用实例字段填充
        async for event, usage in run_query(context, self._messages):
            if usage is not None:
                self._cost_tracker.add(usage)
            yield event
```

### QueryEngine 提供的管理能力

| 方法 | 作用 |
|------|------|
| `messages` | 获取当前对话历史 |
| `total_usage` | 获取累计 token 用量 |
| `clear()` | 清空对话历史和 cost tracker |
| `set_system_prompt(prompt)` | 更新 system prompt |
| `set_model(model)` | 切换模型 |
| `set_permission_checker(checker)` | 更新权限检查器 |
| `load_messages(messages)` | 恢复会话历史（用于 `/resume`） |

---

## 消息模型

> 源码：[`engine/messages.py`](../src/openharness/engine/messages.py)

所有消息使用 Pydantic `BaseModel` 定义，通过 `discriminator="type"` 实现多态：

```python
class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str  # 自动生成 "toolu_{uuid}"
    name: str
    input: dict[str, Any]

class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False

# 联合类型，通过 type 字段区分
ContentBlock = Annotated[
    TextBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type")
]

class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]
```

### API 格式转换

消息模型需要在内部格式和 Anthropic API 格式之间转换：

| 函数 | 方向 |
|------|------|
| `serialize_content_block()` | 内部 → API（发送给 LLM） |
| `assistant_message_from_api()` | API → 内部（解析 LLM 响应） |
| `ConversationMessage.to_api_param()` | 整条消息转 API 格式 |

---

## 流式事件

> 源码：[`engine/stream_events.py`](../src/openharness/engine/stream_events.py)

```python
@dataclass
class AssistantTextDelta:
    text: str                # LLM 输出的文本片段

@dataclass
class AssistantTurnComplete:
    message: ConversationMessage  # 完整的 assistant 消息
    usage: UsageSnapshot          # 本轮 token 用量

@dataclass
class ToolExecutionStarted:
    tool_name: str
    tool_input: dict[str, object]

@dataclass
class ToolExecutionCompleted:
    tool_name: str
    output: str
    is_error: bool
```

这些事件构成了 UI 层实时展示的基础——TUI 前端通过监听这些事件来渲染打字动画、工具执行 spinner 等效果。

---

## QueryContext 数据结构

`QueryContext` 是传入 `run_query()` 的不可变上下文，包含一次 query 所需的所有依赖：

```python
@dataclass
class QueryContext:
    api_client: SupportsStreamingMessages   # API 客户端
    tool_registry: ToolRegistry             # 工具注册表
    permission_checker: PermissionChecker   # 权限检查器
    cwd: Path                               # 工作目录
    model: str                              # 模型名
    system_prompt: str                      # 系统提示词
    max_tokens: int                         # 最大 token 数
    permission_prompt: PermissionPrompt     # 用户确认回调
    ask_user_prompt: AskUserPrompt          # 用户输入回调
    max_turns: int = 8                      # 最大循环轮次
    hook_executor: HookExecutor             # Hook 执行器
    tool_metadata: dict[str, object]        # 额外工具元数据
```

这种设计将所有外部依赖注入到一个 dataclass 中，使得 `run_query()` 成为纯函数式的异步生成器，非常利于测试和复用。
