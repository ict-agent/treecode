# Multi-Agent Web Console Phase 1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落实设计 spec `docs/superpowers/specs/2026-04-06-multi-agent-web-console-design.md` 的 **Phase 1**：树与节点状态在 snapshot 中可版本化对比；WebSocket 断线后自动重连并重新获得全量 snapshot；文档与 CLI 安全说明与 spec 对齐。

**Architecture:** 在现有 `SwarmDebuggerService._projection_payload()` 输出中增加单调递增的 `snapshot_revision`（进程内序号即可）；前端 `SwarmConsoleSnapshot` 类型同步；`WebSocketClient` 增加有限次指数退避重连，重连成功即收到服务端连接握手时发送的 `snapshot`（见 `console_ws.py` 连接建立首包）。不引入新传输协议类型。

**Tech Stack:** Python 3.10+ / Pydantic / websockets；TypeScript / React / Vitest；pytest。

**依据 spec：** §5 架构、§6 Phase 1、§7 安全、§8 重连、§9 测试、§10 协议演进字段。

---

## 文件与职责（Phase 1）

| 路径 | 职责 |
|------|------|
| `src/openharness/swarm/debugger.py` | 在 snapshot payload 中加入 `snapshot_revision` |
| `frontend/terminal/src/shared/swarmConsoleState.ts` | `SwarmConsoleSnapshot` 类型扩展 |
| `frontend/terminal/src/transports/webSocketClient.ts` | 重连、退避、可选 `onConnectionChange` |
| `frontend/terminal/src/web/useSwarmConsole.ts` | 传入重连参数、把连接状态交给 reducer 或本地 state |
| `tests/test_swarm/test_debugger_service.py` 或 `test_console_ws.py` | snapshot 含 revision、重连后仍能收到树数据（能测则测） |
| `frontend/terminal/src/web/__tests__/` 或 `shared/__tests__/` | WebSocketClient mock 行为单测（若可行） |
| `docs/14-Multi-Agent-Web-Console.md` | Phase 1 完成标准、重连行为、`OPENHARNESS_ALLOW_REMOTE_SWARM_CONSOLE` 说明 |
| `docs/superpowers/specs/2026-04-06-multi-agent-web-console-design.md` | 将「状态」改为已定稿/已计划实现（小改） |

---

### Task 1: 后端 `snapshot_revision`

**Files:**
- Modify: `src/openharness/swarm/debugger.py`（`SwarmDebuggerService.__init__`、`_projection_payload`）
- Test: `tests/test_swarm/test_debugger_service.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_swarm/test_debugger_service.py`（若无合适用例则新增 `test_snapshot_includes_monotonic_snapshot_revision`）中：

```python
def test_snapshot_includes_monotonic_snapshot_revision():
    from openharness.swarm.debugger import create_default_swarm_debugger_service

    svc = create_default_swarm_debugger_service()
    a = svc.snapshot()
    b = svc.snapshot()
    assert "snapshot_revision" in a
    assert a["snapshot_revision"] < b["snapshot_revision"]
```

运行：`cd /home/zhangshuoming/workspace/OpenHarness && PYTHONPATH=src uv run pytest tests/test_swarm/test_debugger_service.py::test_snapshot_includes_monotonic_snapshot_revision -v`  
预期：失败（缺字段或断言失败）。

- [ ] **Step 2: 实现**

在 `SwarmDebuggerService.__init__` 末尾增加 `self._snapshot_revision = 0`。

在 `_projection_payload` 中，于 `return {` 之前令 `self._snapshot_revision += 1`，并在返回的 dict 顶层加入 `"snapshot_revision": self._snapshot_revision`（与 `tree`、`overview` 同级）。

- [ ] **Step 3: 运行测试通过**

同上 pytest 命令，预期：PASS。

- [ ] **Step 4: Commit**

```bash
git add src/openharness/swarm/debugger.py tests/test_swarm/test_debugger_service.py
git commit -m "feat(swarm): add snapshot_revision to debugger console snapshot"
```

---

### Task 2: 前端类型与可选 UI 提示

**Files:**
- Modify: `frontend/terminal/src/shared/swarmConsoleState.ts`
- Modify: `frontend/terminal/src/web/WebConsoleView.tsx`（仅当需在 Overview 展示 revision 时；可选，YAGNI 可跳过 UI，仅类型）

- [ ] **Step 1: 扩展类型**

在 `SwarmConsoleSnapshot` 增加可选字段：

```ts
	snapshot_revision?: number;
```

- [ ] **Step 2: （可选）在 Overview 文本中显示 `snapshot_revision`**

若 `WebConsoleView` 已有 Overview 区块，追加一行 `revision: {state.snapshot?.snapshot_revision ?? '—'}`；若无合适位置则本步跳过，仅保留类型。

- [ ] **Step 3: 类型检查**

```bash
cd /home/zhangshuoming/workspace/OpenHarness/frontend/terminal && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add frontend/terminal/src/shared/swarmConsoleState.ts
# 若改了 WebConsoleView：
git add frontend/terminal/src/web/WebConsoleView.tsx
git commit -m "feat(ui): expose snapshot_revision on swarm console snapshot type"
```

---

### Task 3: WebSocket 断线重连

**Files:**
- Modify: `frontend/terminal/src/transports/webSocketClient.ts`
- Modify: `frontend/terminal/src/web/useSwarmConsole.ts`
- Test: 新增 `frontend/terminal/src/transports/__tests__/webSocketClient.test.ts`（若项目已有 Vitest 对 transport 的 mock 模式则跟随；否则用手动测试清单代替并写在 Task 4 文档中）

**行为要求：** 初次 `connect(url, onMessage)` 与现有一致；当 `WebSocket` 触发 `close` 且未调用 `close()` 主动关闭时，按指数退避重连（例如 500ms 起，×2，上限 10s），无限重试或至少 20 次（二选一并在代码注释写明）。每次新连接建立后，服务端 `console_ws` 会在 `_handle_connection` 首包发送 `snapshot`，客户端 `onMessage` 会收到并 `dispatch`，满足「重连 + 全量 snapshot」。

- [ ] **Step 1: 扩展 `WebSocketClient`**

增加私有字段 `_manualClose = false`；`close()` 时设 `_manualClose = true` 并关闭 socket。

`connect` 内：`open` 时清空队列发送；`close` 时若 `!_manualClose` 则 `setTimeout` 调度 `_reconnect()`；`_reconnect` 内重新 `new WebSocket(url)` 并重新绑定相同 `onMessage` 与相同逻辑。

注意：避免在 `close()` 触发的 `close` 事件上重连（`_manualClose` 区分）。

- [ ] **Step 2: `useSwarmConsole`**

确保 `useEffect` 清理时调用 `client.close()`，使组件卸载不重连。

- [ ] **Step 3: 若有 Vitest**：用 mock `WebSocket` 验证：模拟 `close`，断言一段时间后构造新的 open 且 `onMessage` 仍被调用。若 mock 成本过高，在 Task 4 文档中写 **手动 smoke** 步骤代替。

- [ ] **Step 4: Commit**

```bash
git add frontend/terminal/src/transports/webSocketClient.ts frontend/terminal/src/web/useSwarmConsole.ts
git commit -m "feat(ui): auto-reconnect swarm console websocket with backoff"
```

---

### Task 4: 文档与 spec 状态

**Files:**
- Modify: `docs/14-Multi-Agent-Web-Console.md`
- Modify: `docs/superpowers/specs/2026-04-06-multi-agent-web-console-design.md`

- [ ] **Step 1: `docs/14`**

在「当前边界」或新小节 **Phase 1 交付** 中记录：`snapshot_revision` 字段含义；前端重连策略摘要；手动验证：停 `swarm-console` 再启动，浏览器应在重连后恢复树（或刷新后一致）。

在「运行方式」附近增加：**非本机绑定**需 `OPENHARNESS_ALLOW_REMOTE_SWARM_CONSOLE=1`（与 `src/openharness/cli.py` 中 `swarm_console_start` 一致）。

- [ ] **Step 2: design spec**

将文首 **状态** 改为类似：`已定稿；Phase 1 实现见 docs/superpowers/plans/2026-04-06-multi-agent-web-console-phase1.md`。

- [ ] **Step 3: Commit**

```bash
git add docs/14-Multi-Agent-Web-Console.md docs/superpowers/specs/2026-04-06-multi-agent-web-console-design.md
git commit -m "docs: document swarm console phase1 snapshot revision and reconnect"
```

---

### Task 5: 全量验证

- [ ] **Step 1: Python**

```bash
cd /home/zhangshuoming/workspace/OpenHarness && uv run ruff check src tests && uv run pytest -q tests/test_swarm/
```

- [ ] **Step 2: 前端**

```bash
cd /home/zhangshuoming/workspace/OpenHarness/frontend/terminal && npx tsc --noEmit && npx vitest run
```

- [ ] **Step 3: Commit**（仅当有未提交修复时）

---

## Phase 2 / 3（本计划不展开实现）

| 阶段 | 方向 | 提示 |
|------|------|------|
| Phase 2 | 消息图 / mailbox 视图与协议 | 在 `SwarmProjection` / `debugger` payload 中扩展字段，前端新面板 |
| Phase 3 | 工具调用摘要 | 与 `agent_action` / `run_tool` 事件对齐 timeline |

单独开新 spec 补充后再写 `docs/superpowers/plans/YYYY-MM-DD-...-phase2.md`。

---

## Self-review（对照 spec）

1. **Spec coverage：** §6 Phase 1（revision、重连、树可读）→ Task 1–4；§7 安全 → Task 4 文档；§9 测试 → Task 1 + Task 5；§10 协议演进 → `snapshot_revision` 字段。  
2. **Placeholder scan：** 无 TBD；Vitest 可选路径已说明。  
3. **一致性：** `snapshot_revision` 在 Python payload 与 TS 类型同名可选字段。

---

## 执行方式（任选）

计划已保存至 `docs/superpowers/plans/2026-04-06-multi-agent-web-console-phase1.md`。

1. **Subagent-Driven（推荐）** — 每任务派生子 agent，任务间审查。  
2. **Inline Execution** — 本会话按任务顺序执行，配合 executing-plans 的检查点。

若要开始实现，回复倾向方式即可；若你 **auto**，可直接从 Task 1 起在本仓库改代码。
