# Agent 开发与调试指南

本文面向使用 AI agent（如 Cursor、Claude Code 等）或手动方式开发 OpenHarness 的贡献者。它回答"我该怎么安全、有效地改 OpenHarness"这个核心问题。

> 这是 [CLAUDE.md](../CLAUDE.md) 的第一跳展开文档。如果你是首次阅读 OpenHarness 代码，请先读 `CLAUDE.md`。

---

## 你在改什么？确认角色

你是 OpenHarness 的**开发者**，不是它的终端用户。你的改动会影响 OpenHarness 的运行时行为。

三种常见任务类型：

| 任务 | 你在做什么 | 改动范围 |
|------|-----------|---------|
| 改 OpenHarness 本体 | 修改 `src/openharness/` 下的引擎、工具、权限、UI 等 | Python 源码 + 测试 |
| 写运行时 Skill | 为 LLM 编写新的 `.md` 技能文件 | `src/openharness/skills/bundled/content/` 或用户态 `~/.openharness/skills/` |
| 写仓库开发 Skill | 为开发者/外部 agent 编写操作指引 | 仓库根 `skills/` 目录 |

> **关键区分**：运行时 Skill 会被 `load_skill_registry()` 加载并注入到 LLM 上下文中；仓库开发 Skill 不会——它们只是给你（开发者）看的。

---

## 按任务类型的读码路线

### 改 Agent Loop / 核心循环

1. `engine/query.py` — `run_query()` 是整个循环的核心
2. `engine/query_engine.py` — `QueryEngine` 封装消息历史和 `submit_message()`
3. `engine/messages.py` — `ConversationMessage` 和内容块定义
4. `engine/stream_events.py` — 流式事件类型
5. 文档：[docs/02-Agent-Loop引擎.md](02-Agent-Loop引擎.md)

### 改工具系统

1. `tools/base.py` — `BaseTool`, `ToolResult`, `ToolExecutionContext`, `ToolRegistry`
2. `tools/__init__.py` — `create_default_tool_registry()` 注册所有工具
3. 目标工具文件（如 `tools/bash_tool.py`）
4. 文档：[docs/04-工具系统.md](04-工具系统.md)

新增工具的步骤：
1. 在 `tools/` 创建 `xxx_tool.py`，定义 `InputModel`（Pydantic）和 `Tool` 类
2. 在 `tools/__init__.py` 中注册
3. 在 `tests/` 中编写单元测试

### 改 CLI / UI / 入口流程

入口调用链（必须理解）：

```
cli.py:main() → ui/app.py:run_repl()/run_print_mode()
    → ui/runtime.py:build_runtime() + handle_line()
        → engine/query_engine.py:submit_message()
            → engine/query.py:run_query()
```

关键文件：
1. `cli.py` — Typer 参数定义
2. `ui/app.py` — `run_repl()`（交互）和 `run_print_mode()`（非交互）
3. `ui/runtime.py` — `build_runtime()` 组装所有组件
4. `ui/backend_host.py` — React TUI 的 JSON-lines 后端
5. 文档：[docs/12-命令系统与CLI.md](12-命令系统与CLI.md)

### 改 Memory / System Prompt

1. `memory/paths.py` — 路径解析（实际路径：`~/.openharness/data/memory/<project>-<hash>/`）
2. `memory/memdir.py` — `load_memory_prompt()`
3. `prompts/context.py` — `build_runtime_system_prompt()` 是组装的核心
4. `prompts/claudemd.py` — CLAUDE.md 发现逻辑
5. 文档：[docs/09-记忆与上下文.md](09-记忆与上下文.md)

### 改 Swarm 多 Agent 协作

Swarm 是从 Claude Code 移植的多 agent 执行框架，架构分三层：

**执行层**（agent 如何运行）：
1. `swarm/types.py` — `TeammateSpawnConfig`, `SpawnResult`, `TeammateExecutor` 协议
2. `swarm/registry.py` — `BackendRegistry` 自动检测后端（in_process > subprocess > tmux）
3. `swarm/in_process.py` — `InProcessBackend`，用 `contextvars` 隔离同进程多 agent
4. `swarm/subprocess_backend.py` — `SubprocessBackend`，复用 `BackgroundTaskManager`
5. `tools/agent_tool.py` — `agent` 工具，通过 registry 分发 spawn

**通信层**（agent 间如何交互）：
6. `swarm/mailbox.py` — 文件信箱（`~/.openharness/teams/<team>/agents/<id>/inbox/`）
7. `swarm/permission_sync.py` — 权限代理（worker → leader 审批）

**管理层**（团队如何组织）：
8. `swarm/team_lifecycle.py` — 团队持久化（`~/.openharness/teams/<name>/team.json`）
9. `swarm/worktree.py` — Git worktree 隔离
10. `coordinator/agent_definitions.py` — Agent 定义加载（YAML + 内置）
11. `coordinator/coordinator_mode.py` — `TeamRegistry`（内存）+ `CoordinatorMode` 编排

文档：[docs/10-多智能体协调.md](10-多智能体协调.md)

### 改后台任务（底层）

1. `tasks/manager.py` — `BackgroundTaskManager`（被 `SubprocessBackend` 使用）
2. `tasks/types.py` — `TaskRecord`, `TaskType`, `TaskStatus`

---

## 功能成熟度参考

| 子系统 | 成熟度 | 说明 |
|--------|:------:|------|
| Agent Loop (`engine/`) | 稳定 | 核心循环 + auto-compact，max_turns=200 |
| 工具系统 (`tools/`) | 稳定 | 43+ 工具，Pydantic 验证，Schema 生成 |
| 权限系统 (`permissions/`) | 稳定 | 三级模式，路径规则，命令黑名单 |
| Hooks (`hooks/`) | 稳定 | PreToolUse/PostToolUse 生命周期 |
| 技能系统 (`skills/`) | 稳定 | bundled → user → plugins 三级加载 |
| 插件系统 (`plugins/`) | 稳定 | 兼容 claude-code/plugins 格式 |
| 命令系统 (`commands/`) | 稳定 | 54+ 交互命令 |
| Memory (`memory/`) | 稳定 | 跨会话持久化，YAML frontmatter，加权检索 |
| 会话管理 (`services/session_storage.py`) | 稳定 | 快照保存/恢复/导出 |
| Auto-Compaction (`services/compact/`) | 稳定 | microcompact + LLM 摘要，自动触发 |
| CLI (`cli.py`) | 稳定 | Typer 入口，多种输出格式 |
| API 客户端 (`api/`) | 稳定 | Anthropic + OpenAI 兼容（`--api-format openai`） |
| React TUI (`frontend/terminal/`) | 稳定 | React/Ink 前端 |
| MCP (`mcp/`) | 稳定 | Model Context Protocol 客户端 |
| Swarm 执行层 (`swarm/`) | 可用 | InProcessBackend + SubprocessBackend，PaneBackend 类型就绪 |
| 信箱通信 (`swarm/mailbox.py`) | 可用 | 文件信箱，原子写入，fcntl 锁 |
| 权限同步 (`swarm/permission_sync.py`) | 可用 | 文件 + 信箱双路径 |
| 团队生命周期 (`swarm/team_lifecycle.py`) | 可用 | 持久化团队文件 |
| Worktree (`swarm/worktree.py`) | 可用 | Git worktree 隔离 |
| Agent 定义 (`coordinator/agent_definitions.py`) | 可用 | YAML + 内置定义，20+ 配置字段 |
| 后台任务 (`tasks/`) | 稳定 | Shell/Agent 子进程管理，支持重启 |
| Cron (`services/cron_scheduler.py`) | 可用 | 守护进程，`oh cron` 子命令 |
| Agent Debug (`agent_debug.py`) | 可用 | FIFO 无头会话，E2E 测试支持 |
| Bridge (`bridge/`) | 可用 | 前后端桥接会话管理 |

---

## Git 操作指南

### Commit 规范

本仓库使用 **Conventional Commits**：

```
<type>(<scope>): <description>
```

| type | 使用场景 |
|------|---------|
| `feat` | 新功能或新能力 |
| `fix` | 修复 bug |
| `test` | 添加或修改测试 |
| `docs` | 纯文档改动 |
| `chore` | 杂务（依赖更新、脚本维护、CI 调整） |
| `refactor` | 不改变行为的代码重构 |
| `perf` | 性能优化 |

scope 可选但推荐，常用 scope：`engine`, `tools`, `ui`, `debug`, `permissions`, `skills`, `tasks`, `mcp`, `cli`

实际示例（来自仓库历史）：
```
feat(tools): add web screenshot tool
fix(backend): resolve UI deadlock during permission prompts
test(debug): add E2E test suite for agent-debug CLI lifecycle
chore: add session cleanup script and agent-debug skill documentation
feat(ui): toggle JSON streaming and add Ctrl+A shortcut for full_auto mode
```

### 日常 Commit 流程

```bash
# 1. 检查改动范围
git status
git diff --stat

# 2. 选择性暂存（不要 `git add .`，避免混入无关文件）
git add src/openharness/tools/my_tool.py
git add tests/test_my_tool.py

# 3. 确认暂存内容
git diff --staged

# 4. 提交
git commit -m "feat(tools): add my_tool for screenshot capture"
```

### 小修复 Amend 到上一个 Commit

刚提交后发现遗漏文件、小笔误、或 lint 修复，用 amend 合入而不产生新的 commit：

```bash
# 场景 1：补充遗漏的文件
git add src/openharness/tools/my_tool.py
git commit --amend --no-edit

# 场景 2：修正 commit message
git commit --amend -m "feat(tools): add screenshot tool with viewport options"

# 场景 3：lint 自动修复后补充
uv run ruff check src --fix
git add -u
git commit --amend --no-edit
```

**Amend 安全规则**：
- 由于我们纯本地开发不推远端，amend 随时可用，不存在 force push 风险。
- 但如果 amend 的 commit 已经 merge 过其他分支，建议改用新的 `fix:` commit 避免历史混乱。

### .gitignore 管理

当前 `.gitignore` 的重要规则：

```gitignore
.openharness/          # 用户数据（API key、会话、memory），绝不提交
CLAUDE.md              # 当前被 gitignore，仅本地维护
.venv/                 # Python 虚拟环境
__pycache__/           # Python 字节码缓存
frontend/terminal/node_modules/  # 前端依赖
debug.log              # 调试日志
uv.lock                # uv 锁文件
dist/ build/ *.egg-info/  # 构建产物
```

**常用操作**：

```bash
# 检查某文件为什么被 ignore
git check-ignore -v path/to/file

# 强制追踪一个被 ignore 的文件（一次性）
git add -f path/to/ignored/file

# 停止追踪已提交的文件（保留本地文件）
git rm --cached path/to/file
echo "path/to/file" >> .gitignore
git add .gitignore path/to/file   # path/to/file 的删除会被暂存
git commit -m "chore: stop tracking path/to/file"

# 需要新增 ignore 规则时
echo "new-pattern/" >> .gitignore
git add .gitignore
git commit -m "chore: ignore new-pattern directory"
```

**关于 `CLAUDE.md`**：当前在 `.gitignore` 中，改动不会被 git 追踪。如果需要提交 `CLAUDE.md` 的变更：

```bash
# 方式 1：强制添加（不改 .gitignore，仅本次）
git add -f CLAUDE.md
git commit -m "docs: update CLAUDE.md developer guide"

# 方式 2：从 .gitignore 移除（永久追踪）
# 编辑 .gitignore，删除 CLAUDE.md 那行
git add .gitignore CLAUDE.md
git commit -m "chore: start tracking CLAUDE.md"
```

### 分支策略

- **`learn`**：工作分支，所有开发直接在此 commit
- **`main`**：上游分支，只在用户要求时检查并合入新改动

日常开发不需要创建功能分支，也不推送远端，直接在 `learn` 上工作。

当用户要求同步上游 `main` 的改动时：

```bash
# 1. 拉取上游最新
git fetch origin

# 2. 对比差异
git log --oneline origin/main..learn   # learn 比 main 多了什么
git log --oneline learn..origin/main   # main 比 learn 多了什么（待合入）
git diff learn...origin/main --stat    # 文件级别的差异概览

# 3. 确认后合并
git checkout learn
git merge origin/main

# 4. 如果有冲突
#    逐文件解决后 git add <file>，然后 git merge --continue
```

### 撤销与回退

```bash
# 撤销暂存（不丢失改动）
git restore --staged path/to/file

# 丢弃工作区改动（危险，不可恢复）
git restore path/to/file

# 撤销最近一次 commit（保留改动在工作区）
git reset --soft HEAD~1

# 查看某个文件在上次 commit 时的内容
git show HEAD:path/to/file
```

---

## 验证清单

改动后运行以下命令确认无回归：

```bash
# 必须通过（lint + 全量单元测试）
uv run ruff check src tests scripts
uv run pytest -q
```

仅前端改动时：

```bash
cd frontend/terminal && npx tsc --noEmit
```

### 使用 agent-debug 做 E2E 验证

`agent-debug` 是专为外部 agent 设计的无头调试工具。它创建一个持久化的后台会话，通过 FIFO 管道通信：

```bash
# 启动会话
uv run oh agent-debug start my-test

# 设置 full_auto 权限（避免阻塞在权限提示）
uv run oh agent-debug send my-test "/permissions set full_auto"

# 发送测试消息
uv run oh agent-debug send my-test "list files in current directory"

# 检查输出
cat .openharness/sessions/my-test/pretty_output.txt

# 停止会话
uv run oh agent-debug stop my-test
```

输出文件位于 `<cwd>/.openharness/sessions/<id>/`：

| 文件 | 用途 |
|------|------|
| `output` | 原始 NDJSON 事件流（机器可读） |
| `pretty_output.txt` | 过滤后的对话记录（人类可读） |
| `pretty_output_verbose.txt` | 含 LLM API 调用详情（需 `--verbose`） |
| `state.json` | 会话元数据（PID、状态） |
| `input` | FIFO 管道（`send` 命令写入） |

详细使用说明见 [skills/openharness-agent-debug/SKILL.md](../skills/openharness-agent-debug/SKILL.md)。

---

## 关键路径速查

| 概念 | 实际路径 | 来源 |
|------|---------|------|
| 用户配置 | `~/.openharness/` | `config/paths.py:get_config_dir()` |
| 数据目录 | `~/.openharness/data/` | `config/paths.py:get_data_dir()` |
| 用户 Skill | `~/.openharness/skills/` | `skills/loader.py:get_user_skills_dir()` |
| 项目 Memory | `~/.openharness/data/memory/<project>-<hash>/MEMORY.md` | `memory/paths.py:get_memory_entrypoint()` |
| 会话快照 | `~/.openharness/data/sessions/<project>-<hash>/` | `services/session_storage.py` |
| 后台任务输出 | `~/.openharness/data/tasks/<task_id>.log` | `tasks/manager.py` |
| Swarm 团队数据 | `~/.openharness/teams/<name>/` | `swarm/team_lifecycle.py` |
| Swarm 信箱 | `~/.openharness/teams/<team>/agents/<id>/inbox/` | `swarm/mailbox.py` |
| Agent 定义 | `~/.openharness/agent-definitions/` | `coordinator/agent_definitions.py` |
| Agent Debug 会话 | `<cwd>/.openharness/sessions/<id>/` | `agent_debug.py` |
| 设置文件 | `~/.openharness/settings.json` | `config/paths.py:get_config_file_path()` |

---

## 常见陷阱

1. **项目 `.openharness/skills/` 不被加载**：`/init` 创建的 `.openharness/skills/.gitkeep` 只是占位，`load_user_skills()` 只读 `~/.openharness/skills/`。

2. **Memory 路径与 `/init` 创建的不同**：`/init` 在项目下创建 `.openharness/memory/MEMORY.md`，但 `get_memory_entrypoint()` 实际读取 `~/.openharness/data/memory/<project>-<hash>/MEMORY.md`。

3. **会话快照 vs Agent Debug 会话**：前者在 `~/.openharness/data/sessions/`，后者在 `<cwd>/.openharness/sessions/`。

4. **任务输出文件扩展名**：是 `.log`，不是 `.out`。

5. **`agent_tool.py` 现在走 swarm 后端**：不再直接调用 `BackgroundTaskManager.create_agent_task()`，而是通过 `BackendRegistry.get_executor()` 分发。默认优先 `InProcessBackend`。

6. **Swarm 团队数据在 `~/.openharness/teams/`**：不在 `.openharness/` 项目目录下。

7. **`registry.py` 是最大单文件**：修改交互命令时，所有 `/` 命令都在 `commands/registry.py` 中。
