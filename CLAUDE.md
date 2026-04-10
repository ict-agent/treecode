# TreeCode 开发指南

> **上游致谢**：第三方 harness 代码来源与引用方式见仓库根目录 [README.md](README.md) 中的 **Acknowledgements** 一节（仅此一处集中说明）。

> **你不是 TreeCode 本体，你是它的开发者。** 当你阅读此文件时，你正作为外部 agent 或贡献者来维护、改进 TreeCode 这个 AI Agent Harness 框架。`CLAUDE.md` 是你的总入口——它告诉你项目结构、开发约定、以及改动任何子系统前应该先读什么。
>
> 请注意区分：TreeCode 运行时会把这份文件注入到 system prompt 中（通过 `prompts/claudemd.py`），但它的**主要受众是开发者和外部 agent**，而不是 TreeCode 的终端用户。

---

## 快速定位：你要改什么？

先找到你的任务类型，再按表中的路线读码和读文档。

| 改动目标 | 先读的源码 | 对应文档 |
|----------|-----------|---------|
| Agent Loop / 对话循环 | `engine/query.py`, `engine/query_engine.py` | [docs/02-Agent-Loop引擎.md](docs/02-Agent-Loop引擎.md) |
| API 客户端 / Provider | `api/client.py`, `api/provider.py`, `api/openai_client.py` | [docs/03-API客户端与Provider.md](docs/03-API客户端与Provider.md) |
| 工具（新增/修改） | `tools/base.py`, `tools/__init__.py` | [docs/04-工具系统.md](docs/04-工具系统.md) |
| 权限系统 | `permissions/checker.py`, `permissions/modes.py` | [docs/05-权限系统.md](docs/05-权限系统.md) |
| Hooks 生命周期 | `hooks/executor.py`, `hooks/events.py` | [docs/06-Hooks生命周期.md](docs/06-Hooks生命周期.md) |
| 运行时技能（bundled/user） | `skills/loader.py`, `skills/bundled/` | [docs/07-技能系统.md](docs/07-技能系统.md) |
| 插件系统 | `plugins/loader.py`, `plugins/schemas.py` | [docs/08-插件系统.md](docs/08-插件系统.md) |
| Memory / System Prompt | `memory/paths.py`, `prompts/context.py` | [docs/09-记忆与上下文.md](docs/09-记忆与上下文.md) |
| Swarm 多 Agent 协作 | `swarm/`, `tools/agent_tool.py` | [docs/10-多智能体协调.md](docs/10-多智能体协调.md) |
| 后台任务 | `tasks/manager.py` | [docs/10-多智能体协调.md](docs/10-多智能体协调.md) |
| 团队协调 / Agent 定义 | `coordinator/`, `swarm/team_lifecycle.py` | [docs/10-多智能体协调.md](docs/10-多智能体协调.md) |
| 会话持久化 | `services/session_storage.py` | [docs/11-会话管理.md](docs/11-会话管理.md) |
| Auto-Compaction | `services/compact/__init__.py` | [docs/11-会话管理.md](docs/11-会话管理.md) |
| CLI / 命令 / UI | `cli.py`, `ui/app.py`, `ui/runtime.py` | [docs/12-命令系统与CLI.md](docs/12-命令系统与CLI.md) |
| Cron 定时任务 | `services/cron_scheduler.py`, `services/cron.py` | [docs/12-命令系统与CLI.md](docs/12-命令系统与CLI.md) |
| 外部 Agent 调试 TreeCode | `agent_debug.py` | [docs/13-Agent开发与调试指南.md](docs/13-Agent开发与调试指南.md) |

> 所有源码路径均相对于 `src/treecode/`。

---

## 项目定位

**TreeCode** 是一个极简的 AI Agent 基础设施框架，代码量仅 ~11,700 行（Claude Code 的 1/44），但覆盖 98% 的工具能力。

### 核心价值

- **模型提供智能，Harness 提供双手、眼睛、记忆和安全边界**
- 为研究者和开发者理解、实验、扩展 Agent 架构提供开放平台
- 兼容 `anthropics/skills` 和 `claude-code/plugins` 生态

### 关键指标

| 指标 | Claude Code | TreeCode |
|------|-------------|-------------|
| 代码行数 | 512,664 | **11,733** (44x 精简) |
| 文件数 | 1,884 | **163** |
| 工具数 | ~44 | **43** (98%) |
| 命令数 | ~88 | **54** (61%) |
| 测试 | — | **114 unit + 6 E2E** |

---

## 10 大核心子系统

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           TreeCode 架构                                   │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │
│   │  Agent Loop │   │   API      │   │   工具      │   │   权限      │   │
│   │  (engine/)  │◄──│  Client    │   │  (tools/)   │   │  (perms/)   │   │
│   └──────┬──────┘   └─────────────┘   └──────┬──────┘   └─────────────┘   │
│          │                                    │                             │
│          ▼                                    ▼                             │
│   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │
│   │    Hooks    │   │   技能      │   │   插件      │   │    记忆     │   │
│   │  (hooks/)   │   │  (skills/)  │   │  (plugins/) │   │  (memory/)  │   │
│   └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   │
│                                                                            │
│   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   │
│   │ 多智能体    │   │   命令      │   │   CLI/TUI   │   │    MCP      │   │
│   │(coordinator)│   │  (commands) │   │  (cli/ui)   │   │   (mcp/)    │   │
│   └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

| # | 子系统 | 路径 | 核心职责 |
|---|--------|------|----------|
| 1 | **Agent Loop** | `engine/` | 核心对话循环：流式请求 → 工具调用 → 结果拼接 → auto-compact |
| 2 | **API 客户端** | `api/` | Anthropic + OpenAI 兼容 API，指数退避重试 |
| 3 | **工具系统** | `tools/` | 43+ 工具的注册、Schema 生成、执行 |
| 4 | **权限系统** | `permissions/` | 三级模式 + 路径规则 + 命令黑名单 |
| 5 | **Hooks** | `hooks/` | PreToolUse/PostToolUse 生命周期 |
| 6 | **技能系统** | `skills/` | 按需 Markdown 技能加载 |
| 7 | **插件系统** | `plugins/` | claude-code 兼容的插件生态 |
| 8 | **记忆与上下文** | `memory/` + `prompts/` | MEMORY.md + CLAUDE.md + System Prompt |
| 9 | **Swarm 多 Agent** | `swarm/` + `coordinator/` + `tasks/` | 进程内/子进程执行、信箱通信、权限同步、团队生命周期 |
| 10 | **命令与 UI** | `commands/` + `cli.py` | 54 个命令 + Typer CLI + React TUI + Cron |

---

## 核心数据流

```
用户输入
    ↓
cli.py (Typer) —— 解析参数，配置加载
    ↓
ui/app.py —— run_repl() 或 run_print_mode()
    ↓
ui/runtime.py —— build_runtime() 组装 RuntimeBundle
    (API Client + ToolRegistry + Permissions + Hooks + Skills)
    ↓
engine/query_engine.py —— QueryEngine 维护 messages[], cost_tracker
    ↓
┌─────────────────────────────────────────────────────────────────┐
│            engine/query.py — run_query() 核心循环                │
│                                                                 │
│  for turn in range(max_turns):                                 │
│    ┌──► stream_message(messages, tools) ◄─────┐                │
│    │    ├─ yield TextDelta (流式文本)           │                │
│    │    └─ yield MessageComplete (含 tool_uses)│                │
│    │                                           │                │
│    │    if no tool_uses: break                  │                │
│    │                                           │                │
│    │    for each tool_call:                     │                │
│    │      1. PreToolUse Hook 检查               │                │
│    │      2. ToolRegistry.get(name) 查找工具    │                │
│    │      3. Pydantic input_model 验证输入      │                │
│    │      4. PermissionChecker.evaluate() 权限  │                │
│    │      5. tool.execute() 执行                │                │
│    │      6. PostToolUse Hook 通知              │                │
│    └── messages.append(tool_results) ──────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 技能分层说明（重要）

TreeCode 中存在三类"技能"，语义完全不同，不可混淆：

### 1. 运行时内置 Skill（bundled）

- 位置：`src/treecode/skills/bundled/content/*.md`
- 加载方式：`get_bundled_skills()` 在 `skills/bundled/__init__.py` 中扫描 `content/` 目录
- 当前内置：`commit`, `review`, `debug`, `plan`, `test`, `simplify`
- 面向 TreeCode 的终端用户和 LLM，随包分发

### 2. 用户态 Skill（user）

- 位置：`~/.treecode/skills/*.md`（或 `TREECODE_CONFIG_DIR/skills`）
- 加载方式：`load_user_skills()` 在 `skills/loader.py` 中扫描该目录
- 用户自行放入的通用 `.md` 技能，兼容 `anthropics/skills` 格式

### 3. 仓库内开发专用 Skill（repo dev）

- 位置：仓库根 `skills/` 目录（如 `skills/treecode-agent-debug/SKILL.md`）
- **不被** `load_skill_registry()` 加载，不参与运行时
- 面向开发 TreeCode 的 agent 和贡献者，提供调试流程、读码路线等操作指引
- 详见 [docs/13-Agent开发与调试指南.md](docs/13-Agent开发与调试指南.md)

加载优先级（`skills/loader.py:load_skill_registry()`）：

```
bundled → user → plugins（后注册的同名技能覆盖先注册的）
```

> **易混淆点**：`/init` 命令会在项目目录下创建 `.treecode/skills/.gitkeep`，但 `load_user_skills()` 只读取 `~/.treecode/skills/`。项目内的 `.treecode/skills/` 目录当前不参与技能加载。

---

## 关键路径速查

以下路径在开发中最常被误解，以代码实现为准：

| 概念 | 实际路径 | 来源 |
|------|---------|------|
| 用户配置 | `~/.treecode/` | `config/paths.py:get_config_dir()` |
| 数据目录 | `~/.treecode/data/` | `config/paths.py:get_data_dir()` |
| 用户 Skill | `~/.treecode/skills/` | `skills/loader.py:get_user_skills_dir()` |
| 项目 Memory | `~/.treecode/data/memory/<project>-<hash>/MEMORY.md` | `memory/paths.py:get_memory_entrypoint()` |
| 会话快照 | `~/.treecode/data/sessions/<project>-<hash>/` | `services/session_storage.py:get_project_session_dir()` |
| 后台任务输出 | `~/.treecode/data/tasks/<task_id>.log` | `tasks/manager.py` + `config/paths.py:get_tasks_dir()` |
| Agent Debug 会话 | `<cwd>/.treecode/sessions/<id>/` | `agent_debug.py:AGENT_SESSIONS_ROOT` |

---

## 目录结构

```
TreeCode/
├── src/treecode/
│   ├── cli.py                 # CLI 入口 (Typer)
│   ├── __main__.py            # python -m 入口
│   ├── agent_debug.py         # Agent 调试工具
│   │
│   ├── engine/                # Agent Loop 核心
│   │   ├── query.py           # run_query() 核心循环
│   │   ├── query_engine.py    # QueryEngine 高层封装
│   │   ├── messages.py        # 消息模型 (Pydantic)
│   │   ├── stream_events.py   # 流式事件定义
│   │   └── cost_tracker.py    # Token 用量追踪
│   │
│   ├── api/                   # API 客户端
│   │   ├── client.py          # Anthropic 流式客户端 + 重试
│   │   ├── openai_client.py   # OpenAI 兼容客户端（--api-format openai）
│   │   ├── provider.py        # Provider 自动检测
│   │   ├── errors.py          # 自定义异常
│   │   └── usage.py           # UsageSnapshot 统计
│   │
│   ├── tools/                 # 43 个工具
│   │   ├── base.py            # BaseTool + ToolRegistry
│   │   ├── bash_tool.py       # Shell 执行
│   │   ├── file_read_tool.py  # 文件读取
│   │   ├── file_edit_tool.py  # 文件编辑
│   │   ├── skill_tool.py      # skill 工具（按名加载技能内容）
│   │   ├── agent_tool.py      # Agent 生成
│   │   └── ... (37 个)
│   │
│   ├── permissions/           # 权限系统
│   ├── hooks/                 # 生命周期 Hooks
│   ├── skills/                # 运行时技能系统
│   │   ├── loader.py          # 技能加载（bundled → user → plugins）
│   │   ├── registry.py        # SkillRegistry
│   │   └── bundled/content/   # 内置技能 .md 文件
│   │
│   ├── plugins/               # 插件系统
│   ├── memory/                # 持久记忆
│   │   ├── paths.py           # 记忆路径解析
│   │   ├── memdir.py          # MEMORY.md 加载
│   │   ├── manager.py         # 记忆增删
│   │   └── search.py          # 相关记忆检索
│   │
│   ├── prompts/               # System Prompt
│   │   ├── system_prompt.py   # 基础 prompt 构建
│   │   ├── context.py         # 运行时 prompt 组装（核心）
│   │   └── claudemd.py        # CLAUDE.md 发现
│   │
│   ├── tasks/                 # 后台任务
│   │   ├── manager.py         # BackgroundTaskManager
│   │   └── types.py           # TaskRecord, TaskStatus, TaskType
│   │
│   ├── swarm/                 # Swarm 多 Agent 协作（从 Claude Code 移植）
│   │   ├── types.py           # TeammateSpawnConfig, SpawnResult, TeammateExecutor 协议
│   │   ├── registry.py        # BackendRegistry — 自动检测并选择执行后端
│   │   ├── in_process.py      # InProcessBackend — 同进程 asyncio Task 执行
│   │   ├── subprocess_backend.py # SubprocessBackend — 子进程执行
│   │   ├── mailbox.py         # 文件信箱消息队列（leader-worker 通信）
│   │   ├── permission_sync.py # 权限同步协议（worker → leader 权限代理）
│   │   ├── team_lifecycle.py  # 团队持久化管理（~/.treecode/teams/）
│   │   ├── worktree.py        # Git worktree 隔离（每个 teammate 独立工作树）
│   │   └── spawn_utils.py     # 命令构建和环境继承工具
│   │
│   ├── coordinator/           # 多智能体（团队注册 + Agent 定义）
│   │   ├── coordinator_mode.py # TeamRegistry + CoordinatorMode 编排
│   │   └── agent_definitions.py # Agent 定义加载（YAML / 内置）
│   ├── config/                # 配置
│   │   ├── settings.py        # Settings 模型
│   │   └── paths.py           # 路径解析（所有 get_*_dir）
│   │
│   ├── services/              # 服务层
│   │   ├── compact/           # Auto-compaction（microcompact + LLM 摘要）
│   │   ├── session_storage.py # 会话快照持久化
│   │   ├── cron.py            # Cron 任务注册表
│   │   └── cron_scheduler.py  # Cron 调度守护进程
│   ├── commands/              # 54 个交互命令
│   ├── ui/                    # TUI 后端
│   │   ├── app.py             # run_repl() / run_print_mode()
│   │   ├── runtime.py         # build_runtime() / handle_line()
│   │   └── backend_host.py    # React TUI 的 JSON-lines 后端
│   ├── bridge/                # 前后端桥接
│   ├── mcp/                   # MCP 协议
│   └── state/                 # 状态管理
│
├── frontend/terminal/         # React/Ink TUI (17 个组件)
├── tests/                     # 114 unit + 6 E2E
├── scripts/                   # 测试与维护脚本
├── skills/                    # 仓库内开发专用 Skill（不参与运行时加载）
│   └── treecode-agent-debug/SKILL.md
└── docs/                      # 中文架构文档（01-13）
```

---

## 开发原则

### 1. 极简主义
> "44x lighter than Claude Code" 是我们的设计哲学。

- 避免过度抽象，优先简单直接的实现
- 每个工具/模块都有明确的单一职责
- 能用标准库就不引入依赖

### 2. Type Safety
- 使用 Pydantic `BaseModel` 定义所有数据结构和工具输入
- 异步函数返回类型明确标注
- 利用 Python 3.10+ 的类型特性（`list[str]`, `dict[str, Any]`）

### 3. 异步优先
- 所有工具、API 调用、Hook 执行都使用 `async/await`
- 使用 `asyncio.gather()` 并行执行独立操作
- 避免阻塞操作（必要时使用 `asyncio.to_thread()`）

### 4. 测试驱动
- 新工具/功能必须有单元测试
- E2E 测试覆盖核心 CLI 工作流
- 测试命名：`test_<功能>_<场景>_<期望>`

### 5. 兼容性
- API 格式兼容 Anthropic
- Skills 格式兼容 `anthropics/skills`
- Plugins 格式兼容 `claude-code/plugins`

---

## 代码风格

### 导入顺序

```python
# 1. 标准库
import asyncio
import json
from pathlib import Path
from typing import Any

# 2. 第三方库
import httpx
from pydantic import BaseModel, Field

# 3. 本地模块
from treecode.tools.base import BaseTool, ToolResult, ToolExecutionContext
```

### 工具实现模板

```python
from pydantic import BaseModel, Field
from treecode.tools.base import BaseTool, ToolResult, ToolExecutionContext

class MyToolInput(BaseModel):
    param1: str = Field(description="描述")
    param2: int = Field(default=42, ge=0, le=100)

class MyTool(BaseTool):
    name = "my_tool"
    description = "工具的简短描述"
    input_model = MyToolInput

    async def execute(self, arguments: MyToolInput, context: ToolExecutionContext) -> ToolResult:
        # 实现逻辑
        return ToolResult(output="结果", is_error=False)

    def is_read_only(self, arguments: MyToolInput) -> bool:
        return True  # 如果只读
```

### 错误处理

```python
try:
    result = await some_async_operation()
except SomeError as e:
    return ToolResult(
        output=f"Error: {str(e)}",
        is_error=True,
        metadata={"error_type": type(e).__name__}
    )
```

---

## Git 工作流

### Commit 规范

本仓库使用 **Conventional Commits** 格式：

```
<type>(<scope>): <description>

# 示例
feat(tools): add web screenshot tool
fix(engine): prevent infinite loop on empty tool response
test(debug): add E2E test for agent-debug verbose mode
chore: update dependencies
docs: align memory paths with implementation
refactor(ui): simplify backend host event dispatch
```

常用 type：`feat`, `fix`, `test`, `chore`, `docs`, `refactor`, `perf`。scope 可选但推荐。

### 日常 Commit 流程

```bash
# 1. 确认改动
git status
git diff

# 2. 选择性暂存（避免混入无关改动）
git add src/treecode/tools/my_new_tool.py tests/test_my_tool.py

# 3. 提交
git commit -m "feat(tools): add my_new_tool for X"

# 4. 验证
uv run ruff check src tests scripts
uv run pytest -q
```

### 小修复 Amend 到上一个 Commit

当刚提交后发现遗漏或小笔误，用 `--amend` 合入上一个 commit，不产生新的 commit：

```bash
# 修复文件后
git add <fixed-files>
git commit --amend --no-edit     # 保留原 message
# 或
git commit --amend -m "feat(tools): add my_new_tool for X (fix typo)"
```

**限制**：只在本地未推送的 commit 上 amend。已推送到远端的 commit 不要 amend（否则需要 force push）。

### .gitignore 管理

当前 `.gitignore` 的关键规则：

| 规则 | 作用 |
|------|------|
| `.treecode/` | 用户数据目录（API key、会话、memory），绝不提交 |
| `CLAUDE.md` | 当前被 gitignore，仅在本地维护（注意：改动不会被 git 追踪） |
| `.venv/`, `__pycache__/` | Python 运行时产物 |
| `frontend/terminal/node_modules/` | 前端依赖 |
| `debug.log` | 调试日志 |
| `uv.lock` | uv 锁文件 |
| `dist/`, `build/`, `*.egg-info/` | 构建产物 |

**动态调整 `.gitignore`**：

```bash
# 临时追踪一个被 ignore 的文件（如需要提交某个特定文件）
git add -f path/to/ignored/file

# 停止追踪一个已提交的文件（但保留本地文件）
git rm --cached path/to/file
echo "path/to/file" >> .gitignore
git add .gitignore
git commit -m "chore: stop tracking path/to/file"

# 检查某个文件为什么被 ignore
git check-ignore -v path/to/file
```

> **重要**：`CLAUDE.md` 当前在 `.gitignore` 中。如果需要把对 `CLAUDE.md` 的改动提交到仓库，需要先从 `.gitignore` 移除该条目，或使用 `git add -f CLAUDE.md`。

### 分支策略

- **`learn`**：我们的工作分支，所有开发直接在此分支上 commit
- **`main`**：上游分支，只在用户要求时检查是否有新改动可以合入 `learn`

日常开发直接在 `learn` 上 commit，不需要创建功能分支或推送远端。

当用户要求同步上游时：

```bash
git fetch origin
git log --oneline origin/main..learn   # 看 learn 比 main 多了什么
git log --oneline learn..origin/main   # 看 main 比 learn 多了什么
# 确认后合并
git checkout learn
git merge origin/main
```

详细的 git 操作指南见 [docs/13-Agent开发与调试指南.md](docs/13-Agent开发与调试指南.md) 中的"Git 操作指南"一节。

---

## 验证清单

改动后运行以下命令确认无回归：

```bash
# 必须通过
uv run ruff check src tests scripts
uv run pytest -q

# 仅前端改动时需要
cd frontend/terminal && npx tsc --noEmit
```

使用 `agent-debug` 做端到端验证（详见 `skills/treecode-agent-debug/SKILL.md`）：

```bash
uv run treecode agent-debug start my-test
uv run treecode agent-debug send my-test "/permissions set full_auto"
uv run treecode agent-debug send my-test "list files in current directory"
uv run treecode agent-debug stop my-test
```

---

## 常见问题

### Q: 如何添加新工具？

1. 在 `tools/` 创建 `xxx_tool.py`
2. 定义 `InputModel` 和 `Tool` 类
3. 在 `tools/__init__.py` 注册到 `ToolRegistry`
4. 编写单元测试

### Q: 如何添加新的运行时技能？

将 `.md` 文件放入 `src/treecode/skills/bundled/content/`（内置随包分发）或让用户放入 `~/.treecode/skills/`（用户自定义）。

### Q: 如何添加仓库内开发 Skill？

在仓库根 `skills/<skill-name>/SKILL.md` 创建，用于指导外部 agent 如何开发/调试 TreeCode。这些文件**不会**被运行时加载。

### Q: Swarm / Web Console 里怎么稳定创建可回访的子代理？

- 共享 Web Console 现在是**单页多代理视图**：
  - tree 里选 `main@default` → 顶部面板对应主 TreeCode 会话
  - tree 里选 persistent child → 顶部面板切换到该 child 的会话与 transcript
- `/agents` 只负责 shared session 的 swarm tree / selection；后台任务日志与清理由 `/tasks` 负责。
- 当用户要一个**名字明确**的子代理（如 `A`, `A1`, `translator`）时：
  - 用 `agent` 工具
  - `subagent_type` 负责能力/角色类型
  - `agent_name` 负责运行时显示身份
  - `spawn_mode="persistent"` 负责让它留在 tree 中并支持 follow-up
- 不要用 `task_create(local_agent)` 代替 persistent swarm child；那只会创建后台任务，不会成为稳定的 swarm 树节点。
- `oneshot` 适合一次性工作，结束后会从 live tree 消失；`persistent` 适合多轮协作与回访。

### Q: 现在怎么管理“预制 agent”？

- 已有统一的 agent definition 机制：
  - built-in definitions：`src/treecode/coordinator/agent_definitions.py`
  - global definitions：`~/.treecode/agents/*.md`
  - project-local definitions：`.treecode/agents/*.md`
- 解析优先级：
  - project-local `.treecode/agents/`
  - global `~/.treecode/agents/`
  - built-in definitions
- 用户入口是 `/agent-defs`：
  - `/agent-defs` / `list`：列出可复用 profile
  - `/agent-defs show <name>`：查看一个 profile 的说明与关键字段
  - `/agent-defs init <name> [project|global]`：在对应 scope 里生成模板
  - `/agent-defs path`：查看两个目录及其优先级
- 运行时入口是 `/spawn`：
  - `/spawn <profile> <name> <description> [under <agent_id>]`
  - `/spawn` 只创建 `persistent` child
  - `under` 缺省时挂到 `main`
- 感知当前拓扑时：
  - `swarm_context` 用来确认“我是谁、我的 parent/root/lineage 是什么”
  - `swarm_topology(scope="current_session", view="live")` 用来确认“当前这轮 session 的完整 live tree”
  - 不要扫描 `~/.treecode/data/swarm/contexts/` 来重建当前树；那只是历史 cache snapshot
- 要对当前 live direct children 做状态确认 / 握手时：
  - 优先用 `swarm_handshake`
  - 不要临时拼 sender 身份然后 `send_message + task_list` 自己猜谁还活着
- 约定：
  - `subagent_type` 表示能力 profile / 定义名
  - `agent_name` 表示运行时实例身份（例如 `A`, `A1`, `translator`）
- 如果用户说“创建一个叫 A1 的 translator agent”，稳定做法是：
  - profile 用 `subagent_type`
  - 实例名用 `agent_name="A1"`
  - 需要回访/后续消息时用 `spawn_mode="persistent"`

### Q: 如何调试 Agent Loop？

```bash
treecode -p "你的 prompt" --verbose
```

或使用 `agent-debug` CLI 进行无头会话调试：

```bash
uv run treecode agent-debug start <session-id>
uv run treecode agent-debug send <session-id> "你的消息"
uv run treecode agent-debug stop <session-id>
```

详见 [skills/treecode-agent-debug/SKILL.md](skills/treecode-agent-debug/SKILL.md) 和 [docs/13-Agent开发与调试指南.md](docs/13-Agent开发与调试指南.md)。

---

## 相关文档

| # | 文档 | 主题 |
|---|------|------|
| 01 | [架构总览](docs/01-架构总览.md) | 10 大子系统详解 |
| 02 | [Agent-Loop 引擎](docs/02-Agent-Loop引擎.md) | run_query() 核心循环 |
| 03 | [API 客户端与 Provider](docs/03-API客户端与Provider.md) | Anthropic 兼容 API |
| 04 | [工具系统](docs/04-工具系统.md) | 43 个工具分类与实现 |
| 05 | [权限系统](docs/05-权限系统.md) | 三级权限模式 |
| 06 | [Hooks 生命周期](docs/06-Hooks生命周期.md) | PreToolUse/PostToolUse |
| 07 | [技能系统](docs/07-技能系统.md) | 运行时 Skill 加载与优先级 |
| 08 | [插件系统](docs/08-插件系统.md) | 插件生态 |
| 09 | [记忆与上下文](docs/09-记忆与上下文.md) | MEMORY.md + System Prompt 组装 |
| 10 | [多智能体协调](docs/10-多智能体协调.md) | 后台任务 + 团队协调 |
| 11 | [会话管理](docs/11-会话管理.md) | 会话持久化与恢复 |
| 12 | [命令系统与 CLI](docs/12-命令系统与CLI.md) | 54 个命令 + Typer CLI + React TUI |
| 13 | [Agent 开发与调试指南](docs/13-Agent开发与调试指南.md) | 外部 agent 改 TreeCode 的操作手册 |
| — | [SHOWCASE](docs/SHOWCASE.md) | 使用示例 |

---

**记住：你是 TreeCode 的开发者，正在帮助它不断改善。保持精简，保持开放，保持实用。**
