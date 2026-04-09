# Slash 命令与 LLM 上下文

在交互式会话（Textual TUI、React TUI、`--open-web-console` 共享后端）中，每一行输入有两条不同的路径。

## 路径对照

| 输入 | 是否进入 `QueryEngine.messages`（下一轮模型可见） | 界面 transcript |
|------|--------------------------------------------------|----------------|
| **已注册的 `/` 命令**（如 `/gather`、`/version`） | **否** — 由 `ui/runtime.py` 里的命令处理器直接执行，不调用 `submit_message` | `harness`：你输入的那一行；`harness_result`：该命令打印的文本 |
| **以 `/` 开头但未知**（未在 registry 中注册） | **是** — 当作普通用户文本交给 `submit_message` | `user` |
| **普通文本**（不以 `/` 开头） | **是** | `user` |
| 子代理 idle 通知、内部状态等 | 依实现；常见为注入系统侧说明 | `system` |

因此：**你在 main 里打的 `/gather` 不会出现在该会话的 LLM 上下文中**；若希望模型在后续轮次「记得」做过 gather，需要用自然语言再写一句，或等将来支持「可选地把 harness 摘要写回 messages」的机制。

## UI 标记

- **harness / harness (not in LLM)**：已注册 slash 的输入行（Web / 部分 TUI 带简短说明）。
- **harness-out**：该 slash 命令返回的文本输出（同样不进 LLM）。
- **user**：会进入模型的用户消息。
- **system**：系统提示、非 slash 专有的说明等。

实现见 `TranscriptItem` 的 `harness` / `harness_result` 角色（`src/openharness/ui/protocol.py`）及 `SystemPrinter` 的 `harness_output` 标志（`src/openharness/ui/runtime.py`）。

## 与 `/execute` 的关系

`/execute` 会按行重放；其中每一行仍按上表规则：行内若是已注册 slash，则重放时也是 harness 路径，不进 LLM。

## 后续（可选）

若引入「仅当 slash 行带特定标记时才把摘要写入 LLM 上下文」，应单独约定标记语法，并在 `handle_line` 的 slash 分支里在 `submit_message` 与纯 harness 之间分支。
