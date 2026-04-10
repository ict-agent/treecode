# Multi-Agent Web Console 演进设计（树视角 · 与 CLI 并存）

**日期：** 2026-04-06  
**状态：** 已定稿。Phase 1 实现计划：[docs/superpowers/plans/2026-04-06-multi-agent-web-console-phase1.md](../plans/2026-04-06-multi-agent-web-console-phase1.md)

---

## 1. 背景与问题陈述

TreeCode 已具备 Multi-Agent Web Console（WebSocket 后端 + React Web 前端 + `SwarmDebuggerService`），见 `docs/14-Multi-Agent-Web-Console.md`。

本设计约束的是**后续演进方向**，而非从零定义产品：

- **本地 CLI** 以**主 agent 视角**为主（单会话 REPL / 主线程体验）。
- **Web 控制台** 以**整棵 agent 树**为视角，强调全局观测与对多节点的操作。
- 两者 **机制上并存、共用同一套运行时**；差异主要在 **展示方式与操作方式**，不是两套互不相干的后端。
- 未来可能把 Web 侧能力收敛进 CLI 树视图；**本设计周期不包含「把 Web 完整搬进 CLI」**，仅保证演进不堵死该路径。

---

## 2. 目标

1. **可见性优先**：在 Web 端默认能看清 **树结构** 与 **各节点状态**（Phase 1）；再逐步补齐 **消息流**（Phase 2）、**工具/任务级摘要**（Phase 3）。
2. **操控能力**：在现有 `agent_action` 与面板能力基础上延续，与「树视角」一致即可（非本设计独占目标，但可与各阶段联调）。
3. **访问与演进**：**默认仅本机访问**（`127.0.0.1` / `localhost`）；同时在架构与 CLI 参数上 **预留** 将来局域网访问与 **鉴权**（本周期可只落文档与占位，不实现完整生产方案）。

---

## 3. 非目标

- 在本周期内完成「Web 能力 → CLI 树视图」的迁移或对等实现。
- 公网多租户、完整账号体系、生产级安全加固（仅记录风险与扩展点）。
- 用 Web 取代终端 Ink TUI 作为唯一主入口。

---

## 4. 方案比选与结论

| 方案 | 概要 | 优点 | 缺点 |
|------|------|------|------|
| **A. 现有栈增量演进** | 在 `console_ws` + `SwarmDebuggerService` + `WebConsoleView` 上按 Phase 迭代 | 交付快、与现有代码一致 | 若缺少清晰树视图契约，后续 CLI 复用可能返工 |
| **B. 独立「树投影」契约层** | 固定 `TreeSnapshot` 等模型，Web/未来 CLI 只消费聚合结果 | 最利于「机制共存、展示不同」 | 前期抽象与重构成本较高 |
| **C. 协议分叉** | Web 与 CLI 各走各的数据路径 | 短期最快 | 违背「机制共用」，不采纳 |

**结论：** 以 **方案 A 为主**，并吸收 **方案 B 的轻量部分**——在 Phase 1 起，在 `console_protocol` / snapshot 语义中 **明确树状视图所需字段与版本/序号约定**（实现可先挂在现有 `SwarmDebuggerService.snapshot()` 上，不强制拆大模块）。

---

## 5. 架构与数据流（与实现对齐）

**现有骨架（保持，不另起炉灶）：**

- 后端：`src/treecode/swarm/console_protocol.py`、`console_ws.py`、`debugger.py`（`SwarmDebuggerService`）。
- 前端：`frontend/terminal/src/shared/`（含 `swarmConsoleState.ts`、`swarmConsoleProtocol.ts`）、`src/web/WebConsoleView.tsx`、`transports/webSocketClient.ts`。
- 统一操控：`agent_action`（文档已列能力）。

**数据流（概念）：**

- 浏览器通过 WebSocket 连接 `SwarmConsoleWsServer`；连接即 **snapshot**，命令执行后 **广播更新**（与现有模式一致）。
- **树视角** = 在 snapshot/增量里优先保证 **拓扑 + 每节点状态** 完整、可对比（含版本或序号，便于 Phase 2/3 增量与排障）。

---

## 6. 分阶段交付

| 阶段 | 用户价值 | 主要工作方向（概念） |
|------|----------|----------------------|
| **Phase 1** | 一眼看清树与节点状态 | Tree / Overview 与 snapshot 字段对齐；WS 推送与重连后状态一致；场景运行后树仍可读；明确重连后 **再拉 snapshot** 的行为 |
| **Phase 2** | 看清「谁在跟谁说话」 | 消息图 / mailbox 相关视图与协议字段 |
| **Phase 3** | 看清在跑什么工具、任务 | 工具调用摘要、与 `agent_action` / `run_tool` 的展示联动 |

---

## 7. 安全与访问策略

- **默认：** `host=127.0.0.1`，文档与 CLI 帮助中强调本机优先。
- **扩展：** 允许显式绑定 `0.0.0.0` 或局域网 IP；须在文档中说明 **风险**（局域网内明文 WS、无鉴权时的暴露面）。
- **鉴权：** 本周期记录 **占位** 方向（例如：WS 握手 token、仅绑定内网接口、反向代理终止 TLS 等），**不强制**在本周期实现完整方案。

---

## 8. 错误处理与可观测性

- 命令失败：沿用现有 `error` 消息；前端 **Last Error** 与面板内联提示。
- 连接断开：Phase 1 将 **重连 + 全量 snapshot 恢复** 列为可交付行为，避免客户端与后端状态长期分叉。

---

## 9. 测试策略

- **后端：** 延续并加强 `tests/test_swarm/test_console_protocol.py`、`test_console_ws.py`、`test_debugger_service.py` 等；Phase 1 增加/强化 **树快照与广播** 相关断言。
- **前端：** Vitest 覆盖 shared reducer / `WebConsoleView` 关键路径。
- **人工：** 沿用 `docs/14` 中的 smoke 流程；Phase 1 强调 **树与 `agent_count` / 拓扑** 一致性。

---

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| snapshot 体积与频率随树与消息增长而增大 | Phase 2/3 再评估增量、分页或订阅粒度 |
| 协议字段演进 | Phase 1 起在协议与文档中约定 **兼容策略**（例如 snapshot 内版本字段） |

---

## 11. 引用

- 功能说明与运行方式：`docs/14-Multi-Agent-Web-Console.md`
- 多智能体总览：`docs/10-多智能体协调.md`（Multi-Agent Web Console 小节）
