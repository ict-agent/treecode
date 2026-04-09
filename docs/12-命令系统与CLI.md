# 命令系统与 CLI

命令系统提供 54 个内置交互命令，CLI 层基于 Typer 实现完整的命令行界面。

> 对应源码：`src/openharness/commands/registry.py` + `src/openharness/cli.py`

---

## CLI → Runtime → Query Loop 读码路线

理解 OpenHarness 的入口流程是改动 CLI/UI 层的前提。以下是从用户输入到 LLM 调用的完整链路：

```
用户执行 `oh` 或 `python -m openharness`
    ↓
cli.py:main()              # Typer 解析参数
    ├─ 有 -p/--print?      → ui/app.py:run_print_mode()
    └─ 交互模式（默认）      → ui/app.py:run_repl()
                                 ├─ --backend-only?  → ui/backend_host.py:run_backend_host()
                                 └─ 默认              → ui/react_launcher.py:launch_react_tui()
                                                         （内部再启动 --backend-only 子进程）
    ↓
ui/runtime.py:build_runtime()   # 组装 RuntimeBundle
    ├─ load_settings() + merge_cli_overrides()
    ├─ load_plugins() + McpClientManager
    ├─ create_default_tool_registry()
    ├─ HookExecutor
    └─ QueryEngine(api_client, tool_registry, permissions, system_prompt)

ui/runtime.py:start_runtime()   # 执行 SESSION_START hooks
    ↓
用户每行输入 → ui/runtime.py:handle_line()
    ├─ 以 / 开头？ → commands/registry.py 分发到具体命令处理器
    └─ 普通文本    → engine/query_engine.py:submit_message()
                        → engine/query.py:run_query()  # 核心循环
```

已注册的 `/` 命令**不会**调用 `submit_message`，因此**不会进入 LLM 上下文**；界面用 `harness` / `harness_result` 角色区分。详见 [slash-commands-vs-llm-context.md](./slash-commands-vs-llm-context.md)。

**关键文件**（按调用顺序）：

| 顺序 | 文件 | 职责 |
|------|------|------|
| 1 | `cli.py` | Typer 入口，参数解析 |
| 2 | `ui/app.py` | `run_repl()` / `run_print_mode()` 入口分支 |
| 3 | `ui/runtime.py` | `build_runtime()` 组装所有组件，`handle_line()` 处理每行输入 |
| 4 | `ui/backend_host.py` | React TUI 的 JSON-lines 后端（`OHJSON:` 协议） |
| 5 | `engine/query_engine.py` | `submit_message()` 维护消息历史 |
| 6 | `engine/query.py` | `run_query()` 核心循环（流式 API + 工具执行） |

---

## CLI 入口

> 源码：[`cli.py`](../src/openharness/cli.py)

### 入口点配置

```toml
# pyproject.toml
[project.scripts]
openharness = "openharness.cli:app"
oh = "openharness.cli:app"
```

`oh` 和 `openharness` 都指向同一个 Typer 应用。

### 主命令参数

```python
def main(
    ctx: typer.Context,
    # --- 会话 ---
    continue_session: bool,          # -c/--continue  继续上次会话
    resume_session: bool,            # -r/--resume    恢复指定会话
    session_name: str | None,        # -n/--name      会话名称

    # --- 模型 ---
    model: str | None,               # -m/--model     指定模型
    effort: str | None,              # --effort       推理深度
    max_turns: int | None,           # --max-turns    最大循环轮次

    # --- 输出 ---
    print_prompt: str | None,        # -p/--print     非交互模式
    output_format: str | None,       # --output-format text|json|stream-json

    # --- 权限 ---
    permission_mode: str | None,     # --permission-mode
    skip_permissions: bool,          # --dangerously-skip-permissions

    # --- 上下文 ---
    system_prompt: str | None,       # -s/--system-prompt
    append_system_prompt: str | None,# --append-system-prompt
    settings_path: str | None,       # --settings

    # --- 高级 ---
    debug: bool,                     # -d/--debug
    mcp_config: str | None,          # --mcp-config
    bare: bool,                      # --bare

    # --- 隐藏 ---
    backend_only: bool,              # --backend-only (React TUI 后端)
)
```

### 子命令

```python
app = typer.Typer(name="openharness")
mcp_app = typer.Typer(name="mcp", help="Manage MCP servers")
plugin_app = typer.Typer(name="plugin", help="Manage plugins")
auth_app = typer.Typer(name="auth", help="Manage authentication")
agent_debug_app = typer.Typer(name="agent-debug", help="External agent E2E debugging utilities")
swarm_debug_app = typer.Typer(name="swarm-debug", help="Run the lightweight HTML swarm debugger")
swarm_console_app = typer.Typer(name="swarm-console", help="Run the WebSocket backend for the multi-agent web console")

app.add_typer(mcp_app)
app.add_typer(plugin_app)
app.add_typer(auth_app)
app.add_typer(agent_debug_app)
app.add_typer(swarm_debug_app)
app.add_typer(swarm_console_app)
```

| 子命令 | 功能 |
|--------|------|
| `oh mcp list` | 列出 MCP 服务器 |
| `oh mcp add <name> <config>` | 添加 MCP 服务器 |
| `oh mcp remove <name>` | 移除 MCP 服务器 |
| `oh plugin list` | 列出插件 |
| `oh plugin install <source>` | 安装插件 |
| `oh plugin uninstall <name>` | 卸载插件 |
| `oh auth status` | 认证状态 |
| `oh auth login` | 配置认证 |
| `oh auth logout` | 清除认证 |
| `oh agent-debug start <id>` | 启动调试会话 |
| `oh agent-debug send <id> <msg>` | 向调试会话发送消息 |
| `oh agent-debug stop <id>` | 停止调试会话 |
| `oh swarm-debug start` | 启动轻量 HTML 调试页 |
| `oh swarm-console start` | 启动 WebSocket 多智能体控制台后端 |

---

## 命令注册表

> 源码：[`commands/registry.py`](../src/openharness/commands/registry.py)

这是整个项目中最大的单文件，包含 54 个用 `/` 前缀触发的交互命令。

### 54 个命令分类

#### 会话管理

| 命令 | 功能 |
|------|------|
| `/clear` | 清空对话历史 |
| `/compact` | 压缩旧对话历史 |
| `/resume` | 恢复历史会话 |
| `/rewind` | 撤销最近轮次 |
| `/session` | 查看当前会话 |
| `/export` | 导出会话转录 |
| `/share` | 创建可分享快照 |
| `/tag` | 创建命名快照 |

#### 模型和配置

| 命令 | 功能 |
|------|------|
| `/model` | 查看/切换模型 |
| `/config` | 查看/更新配置 |
| `/effort` | 查看/更新推理深度 |
| `/fast` | 查看/更新快速模式 |
| `/passes` | 查看/更新推理轮数 |
| `/output-style` | 查看/更新输出风格 |
| `/theme` | 查看/更新主题 |

#### 权限和安全

| 命令 | 功能 |
|------|------|
| `/permissions` | 查看/切换权限模式 |
| `/plan` | 切换计划模式 |
| `/hooks` | 查看配置的 Hook |

#### 信息和诊断

| 命令 | 功能 |
|------|------|
| `/help` | 显示可用命令 |
| `/version` | 显示版本号 |
| `/doctor` | 环境诊断 |
| `/status` | 会话状态 |
| `/stats` | 会话统计 |
| `/cost` | Token 用量和费用 |
| `/usage` | 使用量估算 |
| `/context` | 查看当前 system prompt |

#### Git 集成

| 命令 | 功能 |
|------|------|
| `/commit` | Git 提交 |
| `/diff` | Git diff |
| `/branch` | 分支信息 |

#### 知识和扩展

| 命令 | 功能 |
|------|------|
| `/skills` | 列出/查看技能 |
| `/memory` | 管理持久记忆 |
| `/plugin` | 管理插件 |
| `/mcp` | 查看 MCP 状态 |

#### 高级功能

| 命令 | 功能 |
|------|------|
| `/agents` | 查看 Agent 和团队任务 |
| `/tasks` | 管理后台任务 |
| `/bridge` | 桥接会话 |
| `/issue` | Issue 上下文 |
| `/pr_comments` | PR 评论上下文 |
| `/files` | 列出工作区文件 |
| `/copy` | 复制最新响应 |
| `/summary` | 总结对话历史 |

#### 其他

| 命令 | 功能 |
|------|------|
| `/exit` | 退出 OpenHarness |
| `/login` | 认证管理 |
| `/logout` | 清除认证 |
| `/init` | 初始化项目文件 |
| `/onboarding` | 快速入门 |
| `/vim` | Vim 模式 |
| `/voice` | 语音模式 |
| `/keybindings` | 快捷键 |
| `/feedback` | 提交反馈 |
| `/privacy-settings` | 隐私设置 |
| `/rate-limit-options` | 限流选项 |
| `/release-notes` | 版本更新说明 |
| `/reload-plugins` | 重新加载插件 |
| `/upgrade` | 升级指南 |

---

## 非交互模式

通过 `-p/--print` 参数进入非交互模式：

```bash
# 纯文本输出
oh -p "Explain this codebase"

# JSON 输出（程序化使用）
oh -p "List all functions in main.py" --output-format json

# 流式 JSON 事件
oh -p "Fix the bug" --output-format stream-json
```

三种输出格式：

| 格式 | 适用场景 |
|------|----------|
| `text` | 终端直接阅读 |
| `json` | 程序解析（完整结果） |
| `stream-json` | 实时消费（每行一个 JSON 事件） |

---

## React TUI 前端

> 源码：`frontend/terminal/src/`（React/Ink）

OpenHarness 提供三种 UI 入口：

### 1. React TUI（默认）

默认路径：`cli.py` → `ui/app.py:run_repl()` → `ui/react_launcher.py:launch_react_tui()`

`launch_react_tui()` 内部启动一个 `python -m openharness --backend-only` 子进程，再通过 Node.js 运行 React/Ink 前端，两者通过 stdin/stdout 的 JSON-lines 协议通信。

### 2. 后端模式（`--backend-only`）

直接运行 Python 后端，输出 `OHJSON:` 前缀的 JSON-lines 事件。适合被外部前端或测试脚本驱动。

```
┌──────────────────┐       stdin/stdout        ┌──────────────────┐
│   Python 后端     │ ◄────────────────────────► │  React/Ink TUI   │
│ (oh --backend-only)│   OHJSON: JSON-lines     │  (node terminal) │
└──────────────────┘                             └──────────────────┘
```

```
frontend/terminal/
├── src/
│   ├── shared/            # 状态、协议、selector
│   ├── terminal/          # Ink renderer
│   ├── web/               # React DOM renderer
│   ├── transports/        # stdio / WebSocket transport
│   └── ...                # 其他组件与入口
├── package.json           # React + Ink + Vite 依赖
└── tsconfig.json
```

---

## Multi-Agent Web Console

在 React TUI 之外，Swarm 还可以通过浏览器侧控制台来运行：

### 1. 启动 WebSocket 后端

```bash
oh swarm-console start --host 127.0.0.1 --port 8766
```

### 2. 启动 Web 前端

```bash
cd frontend/terminal
VITE_SWARM_CONSOLE_WS_URL=ws://127.0.0.1:8766 npm run dev:web
```

### 3. 主要能力

- session dashboard
- deterministic scenario run
- tree / overview / activity / scenario view
- approval resolve
- unified `agent_action`
- synthetic/live spawn
- topology edit / context patch
- archive / compare

详见：[docs/14-Multi-Agent-Web-Console.md](14-Multi-Agent-Web-Console.md)

---

## Bridge 桥接层

> 源码：`src/openharness/bridge/`

Bridge 模块负责管理前后端之间的通信：

| 文件 | 职责 |
|------|------|
| `manager.py` | 桥接会话管理 |
| `session_runner.py` | 会话运行器 |
| `types.py` | 桥接类型定义 |
| `work_secret.py` | 工作密钥（安全通信） |

---

## 设计要点

1. **Typer 分层**：主命令 + 多个子命令组（mcp/plugin/auth/agent-debug/swarm-debug/swarm-console）
2. **命令模式统一**：所有 `/` 命令在 `registry.py` 中注册
3. **三种输出格式**：text/json/stream-json 适应不同使用场景
4. **双前端渲染架构**：Ink terminal + React DOM web，共享 `frontend/terminal/src/shared/`
5. **双协议**：单会话 TUI 使用 `OHJSON:` JSON-lines，多智能体控制台使用 WebSocket
