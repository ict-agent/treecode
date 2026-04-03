# 命令系统与 CLI

命令系统提供 54 个内置交互命令，CLI 层基于 Typer 实现完整的命令行界面。

> 对应源码：`src/openharness/commands/registry.py` + `src/openharness/cli.py`

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

app.add_typer(mcp_app)
app.add_typer(plugin_app)
app.add_typer(auth_app)
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

---

## 命令注册表

> 源码：[`commands/registry.py`](../src/openharness/commands/registry.py)

这是整个项目中最大的单文件（64KB），包含 54 个用 `/` 前缀触发的交互命令。

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

OpenHarness 提供两种 UI 模式：

### 1. 简化 CLI（默认）

使用 `rich` + `prompt-toolkit` 实现的文本界面。

### 2. React TUI（`--backend-only`）

```
frontend/terminal/
├── src/
│   ├── App.tsx            # 主应用
│   ├── ChatView.tsx       # 对话视图
│   ├── InputBar.tsx       # 输入栏
│   ├── PermDialog.tsx     # 权限确认对话框
│   ├── CommandPicker.tsx  # 命令选择器
│   ├── Spinner.tsx        # 加载动画
│   └── ...               # 更多组件
├── package.json           # React + Ink 依赖
└── tsconfig.json
```

后端通过 `--backend-only` 启动 WebSocket 服务，前端通过 WebSocket 连接：

```
┌──────────────────┐         WebSocket         ┌──────────────────┐
│   Python 后端     │ ◄────────────────────────► │  React/Ink TUI   │
│   (oh --backend)  │    JSON-RPC messages       │  (node terminal) │
└──────────────────┘                             └──────────────────┘
```

---

## UI 后端协议

> 源码：`src/openharness/ui/`（10 个文件）

UI 后端通过 WebSocket 暴露以下能力：
- 会话管理（创建、恢复、清空）
- 消息发送与流式接收
- 工具执行状态通知
- 权限确认对话
- 命令执行

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

1. **Typer 分层**：主命令 + 3 个子命令组（mcp/plugin/auth）
2. **命令模式统一**：所有 `/` 命令在 `registry.py` 中注册
3. **三种输出格式**：text/json/stream-json 适应不同使用场景
4. **双 UI 架构**：简化 CLI + React TUI，共享同一后端
5. **WebSocket 协议**：前后端解耦，支持远程连接
