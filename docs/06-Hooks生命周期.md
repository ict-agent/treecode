# Hooks 生命周期

Hooks 系统在工具执行前后插入自定义逻辑——支持 4 种 Hook 类型：命令、HTTP、Prompt、Agent。

> 对应源码：`src/treecode/hooks/`

---

## 模块组成

| 文件 | 职责 |
|------|------|
| `events.py` | `HookEvent` 枚举（PRE_TOOL_USE / POST_TOOL_USE） |
| `executor.py` | `HookExecutor` — 核心执行引擎 |
| `loader.py` | `HookRegistry` — Hook 注册表加载 |
| `schemas.py` | Hook 定义 Pydantic 模型 |
| `types.py` | `HookResult` / `AggregatedHookResult` 结果类型 |
| `hot_reload.py` | Hook 配置热重载 |

---

## Hook 事件

```python
class HookEvent(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"     # 工具执行前
    POST_TOOL_USE = "post_tool_use"   # 工具执行后
```

在 Agent Loop 中的触发点：

```
_execute_tool_call():
    ├── HookEvent.PRE_TOOL_USE   ← 可以阻止工具执行
    ├── (工具实际执行)
    └── HookEvent.POST_TOOL_USE  ← 通知执行结果
```

---

## 4 种 Hook 类型

### 1. Command Hook — 执行本地命令

> 类型：`CommandHookDefinition`

通过 `asyncio.create_subprocess_exec` 执行 bash 命令，根据退出码判断成功/失败：

```python
async def _run_command_hook(self, hook, event, payload):
    command = _inject_arguments(hook.command, payload)

    process = await asyncio.create_subprocess_exec(
        "/bin/bash", "-lc", command,
        cwd=str(self._context.cwd),
        env={
            **os.environ,
            "TREECODE_HOOK_EVENT": event.value,       # 事件名
            "TREECODE_HOOK_PAYLOAD": json.dumps(payload),  # 完整 payload
        },
    )

    stdout, stderr = await asyncio.wait_for(
        process.communicate(),
        timeout=hook.timeout_seconds,  # 超时保护
    )

    success = process.returncode == 0
    return HookResult(
        success=success,
        blocked=hook.block_on_failure and not success,  # 可配置阻止
    )
```

**关键特性**：
- 通过环境变量传入事件名和 payload
- `$ARGUMENTS` 模板变量会被替换为 JSON payload
- 支持超时（超时 → `process.kill()`）
- `block_on_failure` 可配置是否在失败时阻止工具执行

### 2. HTTP Hook — 发送 HTTP 请求

> 类型：`HttpHookDefinition`

```python
async def _run_http_hook(self, hook, event, payload):
    async with httpx.AsyncClient(timeout=hook.timeout_seconds) as client:
        response = await client.post(
            hook.url,
            json={"event": event.value, "payload": payload},
            headers=hook.headers,
        )
    success = response.is_success
    return HookResult(success=success, blocked=hook.block_on_failure and not success)
```

用于集成外部审计服务、安全扫描 API 等。

### 3. Prompt Hook — LLM 判断

> 类型：`PromptHookDefinition`

```python
async def _run_prompt_like_hook(self, hook, event, payload, *, agent_mode):
    prompt = _inject_arguments(hook.prompt, payload)

    prefix = "You are validating whether a hook condition passes in TreeCode. "
              "Return strict JSON: {\"ok\": true} or {\"ok\": false, \"reason\": \"...\"}."

    request = ApiMessageRequest(
        model=hook.model or self._context.default_model,
        messages=[ConversationMessage.from_user_text(prompt)],
        system_prompt=prefix,
        max_tokens=512,
    )

    # 调用 LLM
    async for event_item in self._context.api_client.stream_message(request):
        ...

    # 解析 JSON 响应
    parsed = _parse_hook_json(text)
    if parsed["ok"]:
        return HookResult(success=True)
    else:
        return HookResult(success=False, blocked=hook.block_on_failure)
```

**使用 LLM 来做判断**——例如安全审查："这个文件编辑是否可能引入安全漏洞？"

### 4. Agent Hook — 深度 LLM 判断

> 类型：`AgentHookDefinition`

与 Prompt Hook 相同实现，仅 system prompt 增加 "Be more thorough and reason over the payload before deciding."，要求 LLM 更深入推理。

---

## Hook 匹配逻辑

> 源码：`executor.py:_matches_hook()`

```python
def _matches_hook(hook, payload):
    matcher = getattr(hook, "matcher", None)
    if not matcher:
        return True  # 无 matcher → 匹配所有

    # 从 payload 中取匹配对象
    subject = str(
        payload.get("tool_name")
        or payload.get("prompt")
        or payload.get("event")
        or ""
    )
    return fnmatch.fnmatch(subject, matcher)
```

例如配置 `matcher: "bash"` 只针对 bash 工具执行 Hook，或 `matcher: "edit_*"` 匹配所有编辑类工具。

---

## 模板变量注入

```python
def _inject_arguments(template: str, payload: dict) -> str:
    return template.replace("$ARGUMENTS", json.dumps(payload))
```

在 Hook 的 `command` 或 `prompt` 中使用 `$ARGUMENTS` 占位符，运行时被替换为完整的 JSON payload：

```json
{
  "tool_name": "bash",
  "tool_input": {"command": "rm -rf /tmp/test"},
  "event": "pre_tool_use"
}
```

---

## HookResult 结果

```python
@dataclass
class HookResult:
    hook_type: str          # "command" / "http" / "prompt" / "agent"
    success: bool           # 是否成功
    output: str = ""        # 输出文本
    blocked: bool = False   # 是否阻止后续操作
    reason: str = ""        # 阻止原因
    metadata: dict = ...    # 额外元数据（如 returncode, status_code）

@dataclass
class AggregatedHookResult:
    results: list[HookResult]

    @property
    def blocked(self) -> bool:
        return any(r.blocked for r in self.results)

    @property
    def reason(self) -> str | None:
        for r in self.results:
            if r.blocked:
                return r.reason
        return None
```

当任一 Hook 返回 `blocked=True` 时，工具执行被阻止。

---

## Hook 配置方式

### 1. 项目级配置

创建 `.treecode/hooks.json`：

```json
{
  "pre_tool_use": [
    {
      "type": "command",
      "command": "echo 'Checking: $ARGUMENTS'",
      "matcher": "bash",
      "timeout": 10,
      "block_on_failure": true
    }
  ]
}
```

### 2. 通过插件

插件可以在 `hooks/hooks.json` 中定义 Hook（详见 [08-插件系统](./08-插件系统.md)）。

### 3. 热重载

> 源码：`hooks/hot_reload.py`

Hook 配置支持热重载——修改 `hooks.json` 后无需重启，`HookExecutor.update_registry()` 会自动更新。

---

## 与 Agent Loop 的集成

在 `engine/query.py:_execute_tool_call()` 中：

```python
# PreToolUse
if context.hook_executor is not None:
    pre_hooks = await context.hook_executor.execute(
        HookEvent.PRE_TOOL_USE,
        {"tool_name": tool_name, "tool_input": tool_input, "event": "pre_tool_use"},
    )
    if pre_hooks.blocked:
        return ToolResultBlock(content=pre_hooks.reason, is_error=True)

# ... 工具执行 ...

# PostToolUse
if context.hook_executor is not None:
    await context.hook_executor.execute(
        HookEvent.POST_TOOL_USE,
        {"tool_name": ..., "tool_output": ..., "tool_is_error": ..., ...},
    )
```
