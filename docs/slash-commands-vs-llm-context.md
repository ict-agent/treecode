# Slash 命令与 LLM 上下文

在交互式会话（Textual TUI、React TUI、`--open-web-console` 共享后端）中，每一行输入有两条不同的路径。

## 路径对照

| 输入 | 是否进入 `QueryEngine.messages`（下一轮模型可见） | 界面 transcript |
|------|--------------------------------------------------|----------------|
| **已注册的 `/` 命令**（如 `/gather`、`/version`） | **默认否** — 由 `ui/runtime.py` 里的命令处理器直接执行，不调用 `submit_message` | `harness`：你输入的那一行；`harness_result`：该命令打印的文本 |
| **已注册 slash + 行尾 ` !!`** | **是** — 命令仍由 Harness 执行；结束后追加一条 **user** 消息，内含命令行与输出摘要（见下） | 同上（整行仍含 ` !!`） |
| **以 `/` 开头但未知**（未在 registry 中注册） | **是** — 当作普通用户文本交给 `submit_message` | `user` |
| **普通文本**（不以 `/` 开头） | **是** | `user` |
| 子代理 idle 通知、内部状态等 | 依实现；常见为注入系统侧说明 | `system` |

### 统一标记：行尾 ` !!`（空格 + 两个英文叹号）

- 仅当 **去掉 ` !!` 后的前缀** 能匹配 **已注册** 的 slash 时生效；否则整行仍按普通输入处理（未知 slash 不会误剥后缀）。
- **必须**在 `!!` 前有空格，以避免与参数内容混淆（例如 `/version!!` 不会触发）。
- 计入上下文的内容格式见 `QueryEngine.append_slash_command_for_model_context`（`src/openharness/engine/query_engine.py`）：前缀 `[Slash command recorded for model context]` + 命令行 + 输出（过长会截断）。

成功写入后，会话里会再出现一行 **system** 提示（`Recorded slash output in LLM context…`），避免你只看到 harness 输出却以为「没触发」。该摘要**不会**再以第二条 harness 气泡重复整段命令输出。

### `/gather` 与递归子代理

若父节点使用 `/gather ... !!`，则发往子节点的委托行（含递归 fan-out）也会在末尾附带 ` !!`，使 **每个执行该 slash 的 agent** 在本地会话里同样把本次 gather 记入 LLM 上下文（实现：`src/openharness/tools/swarm_gather_tool.py` 与 `src/openharness/swarm/gather.py` 中的委托命令构造）。

## UI 标记

- **harness / harness (not in LLM)**：已注册 slash 的输入行（Web / 部分 TUI 带简短说明）。
- **harness-out**：该 slash 命令返回的文本输出（默认同样不进 LLM；若使用 ` !!` 则另有一条 user 摘要进入上下文）。
- **user**：会进入模型的用户消息（含可选的 slash 摘要）。
- **system**：系统提示、非 slash 专有的说明等。

实现见 `TranscriptItem` 的 `harness` / `harness_result` 角色（`src/openharness/ui/protocol.py`）及 `SystemPrinter` 的 `harness_output` 标志（`src/openharness/ui/runtime.py`）。行尾 ` !!` 的解析见 `strip_slash_remember_suffix`（`src/openharness/ui/runtime.py`）。

## 与 `/execute` 的关系

`/execute` 会按行重放；其中每一行仍按上表规则：某行若以已注册 slash 结尾 ` !!`，重放时同样会把该行的输出记入 **当时会话** 的 LLM 上下文。
