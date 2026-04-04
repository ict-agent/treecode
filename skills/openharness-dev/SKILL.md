---
name: openharness-dev
description: >-
  开发 OpenHarness 的操作指引：读码路线、架构导航、验证清单和常见陷阱。
  面向外部 agent 和贡献者，帮助安全有效地修改 OpenHarness 代码。
---

# OpenHarness 开发 Skill

当你需要修改、扩展或调试 OpenHarness 自身时，使用本 skill。

> 本 skill 是仓库内开发专用的，**不被** OpenHarness 运行时加载。它与运行时 bundled skill（如 commit、review）是完全不同的概念。

---

## 入口文档

改动前先读以下两个文件：

1. **CLAUDE.md**（仓库根目录）— 总导航：项目定位、子系统列表、任务路由表、技能分层、代码风格
2. **docs/13-Agent开发与调试指南.md** — 展开指南：读码路线、功能成熟度、验证清单、常见陷阱

---

## 快速任务路由

| 改动目标 | 先读的源码（`src/openharness/` 下） | 对应文档 |
|----------|------|------|
| Agent Loop | `engine/query.py`, `engine/query_engine.py` | `docs/02` |
| API 客户端 | `api/client.py`, `api/openai_client.py` | `docs/03` |
| 工具 | `tools/base.py`, `tools/__init__.py` | `docs/04` |
| 权限 | `permissions/checker.py` | `docs/05` |
| Hooks | `hooks/executor.py` | `docs/06` |
| 运行时 Skill | `skills/loader.py` | `docs/07` |
| 插件 | `plugins/loader.py` | `docs/08` |
| Memory / Prompt | `memory/paths.py`, `prompts/context.py` | `docs/09` |
| Swarm 多 Agent | `swarm/`, `tools/agent_tool.py` | `docs/10` |
| 后台任务 | `tasks/manager.py` | `docs/10` |
| 会话 / Compact | `services/session_storage.py`, `services/compact/` | `docs/11` |
| CLI / UI / Cron | `cli.py`, `ui/app.py`, `services/cron_scheduler.py` | `docs/12` |

---

## 技能分层（三类不可混淆）

| 类型 | 位置 | 运行时加载？ |
|------|------|:---:|
| 运行时内置 | `src/openharness/skills/bundled/content/*.md` | 是 |
| 用户态 | `~/.openharness/skills/*.md` | 是 |
| 仓库开发专用 | 仓库根 `skills/` | 否 |

---

## 验证清单

改动后运行：

```bash
uv run ruff check src tests scripts
uv run pytest -q
```

前端改动追加：

```bash
cd frontend/terminal && npx tsc --noEmit
```

E2E 验证（详见 `skills/openharness-agent-debug/SKILL.md`）：

```bash
uv run oh agent-debug start test-session
uv run oh agent-debug send test-session "/permissions set full_auto"
uv run oh agent-debug send test-session "你的测试 prompt"
uv run oh agent-debug stop test-session
```

---

## 关键路径速查

| 概念 | 实际路径 |
|------|---------|
| 用户配置 | `~/.openharness/` |
| 数据目录 | `~/.openharness/data/` |
| 用户 Skill | `~/.openharness/skills/` |
| 项目 Memory | `~/.openharness/data/memory/<project>-<hash>/MEMORY.md` |
| 会话快照 | `~/.openharness/data/sessions/<project>-<hash>/` |
| 后台任务输出 | `~/.openharness/data/tasks/<task_id>.log` |
| Swarm 团队数据 | `~/.openharness/teams/<name>/` |
| Swarm 信箱 | `~/.openharness/teams/<team>/agents/<id>/inbox/` |
| Agent Debug 会话 | `<cwd>/.openharness/sessions/<id>/` |

---

## 常见陷阱

1. 项目内 `.openharness/skills/` **不被运行时加载**（只有 `~/.openharness/skills/` 会）
2. Memory 入口文件在 `~/.openharness/data/memory/<project>-<hash>/MEMORY.md`，不在项目 `.openharness/memory/` 下
3. 任务输出是 `.log`，不是 `.out`
4. `agent_tool.py` 现在走 swarm 后端（`BackendRegistry`），不再直接调 `BackgroundTaskManager`
5. Swarm 团队数据在 `~/.openharness/teams/`，不在项目目录下

---

## Git 速查

**Commit 格式**：`<type>(<scope>): <description>`，type 包括 `feat`, `fix`, `test`, `docs`, `chore`, `refactor`

```bash
# 选择性暂存 + 提交
git add <files>
git commit -m "feat(tools): add new tool"

# 小修复 amend（仅未推送的 commit）
git add <fixed-files>
git commit --amend --no-edit

# .gitignore 调试
git check-ignore -v path/to/file

# 强制追踪被 ignore 的文件
git add -f path/to/file
```

**注意**：`CLAUDE.md` 当前在 `.gitignore` 中。提交 CLAUDE.md 改动需要 `git add -f CLAUDE.md`。

详细 git 操作指南见 [docs/13-Agent开发与调试指南.md](../../docs/13-Agent开发与调试指南.md) 中的"Git 操作指南"一节。

---

## 相关 Skill

- **[openharness-agent-debug](../openharness-agent-debug/SKILL.md)** — `oh agent-debug` 子命令的完整使用指南，用于 E2E 测试和行为追踪
