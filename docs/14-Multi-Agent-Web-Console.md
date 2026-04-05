# Multi-Agent Web Console

OpenHarness 现在提供一个面向多智能体运行时的 Web 控制台，用于观察、控制、编辑、归档和比较多 agent 树状执行。

> 对应源码：`frontend/terminal/` + `src/openharness/swarm/console_*.py` + `src/openharness/swarm/debugger.py`

---

## 目标

这个控制台不是简单把已有终端 UI 搬到浏览器里，而是把多智能体运行时变成一个可操作的系统：

- 观察 agent 树、消息图、运行指标、审批队列
- 直接从前端创建 agent、暂停/恢复/停止 agent
- 修改上下文、调整拓扑、触发固定场景
- 对多次运行做归档和比较

---

## 整体架构

```mermaid
flowchart LR
    subgraph frontend [frontend/terminal]
        sharedCore[sharedCore]
        terminalRenderer[terminalRenderer]
        webRenderer[webRenderer]
        transports[transports]
        sharedCore --> terminalRenderer
        sharedCore --> webRenderer
        transports --> sharedCore
    end

    subgraph backend [src/openharness/swarm]
        consoleProtocol[consoleProtocol]
        consoleWs[consoleWs]
        debuggerService[SwarmDebuggerService]
        manager[AgentManager]
        archives[RunArchiveStore]
    end

    webRenderer --> consoleProtocol
    consoleProtocol --> consoleWs
    consoleWs --> debuggerService
    debuggerService --> manager
    debuggerService --> archives
```

---

## 前端结构

Web console 复用 `frontend/terminal` 目录，但不是让 Ink 和 DOM 共用一套渲染组件，而是拆成 shared core 和两个 renderer：

### Shared Core

- `frontend/terminal/src/shared/replSession.ts`
  - 单会话 REPL/TUI 的共享 reducer
- `frontend/terminal/src/shared/swarmConsoleState.ts`
  - 多 agent console 的共享状态
- `frontend/terminal/src/shared/swarmConsoleProtocol.ts`
  - 前端命令与服务端消息类型

### Terminal Renderer

- `frontend/terminal/src/terminal/TerminalApp.tsx`
  - 作为 Ink 入口壳层
- `frontend/terminal/src/hooks/useBackendSession.ts`
  - 基于 shared reducer 的 terminal transport

### Web Renderer

- `frontend/terminal/src/web/WebApp.tsx`
- `frontend/terminal/src/web/WebConsoleView.tsx`
- `frontend/terminal/src/web/useSwarmConsole.ts`

### Transports

- `frontend/terminal/src/transports/webSocketClient.ts`
  - 浏览器侧 WebSocket client

---

## 后端结构

### WebSocket 协议与服务

- `src/openharness/swarm/console_protocol.py`
  - 控制台 WS 消息模型
- `src/openharness/swarm/console_ws.py`
  - WebSocket server

### 控制台域服务

- `src/openharness/swarm/debugger.py`
  - 控制台后端主入口，负责：
    - snapshot / playback
    - agent control
    - approval resolve
    - context patch
    - scenario run
    - archive / compare
    - unified `agent_action`

### 固定场景与树管理

- `src/openharness/swarm/manager.py`
  - 不依赖模型行为的 deterministic 场景和 synthetic tree 操作

### 运行归档

- `src/openharness/swarm/run_archive.py`
  - run 级归档、列出历史 run、比较两次 run

---

## 统一 Agent 操作模型

Web console 不再只依赖一堆分散命令，而是通过统一的 `agent_action` 机制驱动任意 agent：

当前已支持：

- `inspect`
- `send_message`
- `spawn_child`
- `pause`
- `resume`
- `stop`
- `reparent`
- `remove`
- `patch_context`
- `run_tool`

其中 `run_tool` 允许控制台代表某个 agent 执行一次真实工具调用，目前优先覆盖无副作用或低副作用工具。

---

## 固定场景

当前内置 deterministic 场景：

| 场景 | 说明 |
|------|------|
| `single_child` | `main -> sub1` |
| `two_level_fanout` | `main -> sub1 -> (A, B)` |
| `approval_on_leaf` | 在 `two_level_fanout` 基础上给叶子节点制造审批事件 |

这些场景的目的不是测试模型能力，而是稳定测试：

- 树结构
- agent 间消息
- 审批流
- 前端聚合展示
- archive / compare

---

## 当前前端面板

当前 WebConsoleView 已经有：

- `Overview`
- `Scenario View`
- `Tree`
- `Agent Activity`
- `Approvals`
- `Inject Message`
- `Agent Control`
- `Spawn Agent`
- `Topology Editor`
- `Context Editor`
- `Agent Operations`
- `Run Archives`
- `Compare Runs`
- `Last Action Result`
- `Last Error`

其中 `Agent Operations` 是对任意 agent 的统一操作入口。

---

## 运行方式

### 启动 WebSocket 后端

```bash
cd /path/to/OpenHarness
PYTHONPATH=src uv run python -m openharness swarm-console start --host 127.0.0.1 --port 8766
```

### 启动 Web 前端

```bash
cd frontend/terminal
VITE_SWARM_CONSOLE_WS_URL=ws://127.0.0.1:8766 npm run dev:web
```

### 构建

```bash
cd frontend/terminal
npx tsc --noEmit
npm run build:web
```

---

## 验证建议

### 后端测试

```bash
PYTHONPATH=src uv run pytest -q \
  tests/test_swarm/test_console_protocol.py \
  tests/test_swarm/test_console_ws.py \
  tests/test_swarm/test_manager.py \
  tests/test_swarm/test_debugger_service.py
```

### 前端测试

```bash
cd frontend/terminal
npx vitest run \
  src/shared/__tests__/replSessionReducer.test.ts \
  src/shared/__tests__/swarmConsoleState.test.ts \
  src/web/__tests__/WebConsoleView.test.tsx
```

### 推荐 smoke test

1. 启动 `swarm-console`
2. 启动 web 前端
3. 在页面里运行 `two_level_fanout`
4. 确认：
   - `Overview.agent_count == 4`
   - `Scenario View` 里有三层：`main`、`sub1`、`A/B`
   - `Tree` 中 `main -> sub1 -> A/B`
   - `Agent Activity` 中 `sub1.children == [A, B]`
5. 运行 `approval_on_leaf`
6. 在页面里点击 `Approve` / `Reject`
7. 归档当前 run，再切换另一个场景后做 compare

---

## 当前边界

当前版本已经具备第一版多智能体控制台的核心骨架，但仍属于 MVP：

- 前端交互和视觉样式还可继续打磨
- WebSocket client 还缺更完善的重连和状态反馈
- `run_tool` 已打通，但更深入的 tool-call 级管理仍可继续扩展
- terminal renderer 与 shared core 的彻底收口仍可继续推进
