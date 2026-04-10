# Swarm Agent 拓扑：全局可见性 — 问题梳理与实现待办

> **用途**：把「N 叉树 + 分布式入口修改」想清楚，记录现象与计划改法。  
> **状态**：实现中。Phase A 语义已落文档；Phase B / C 正在按本文推进。

---

## 1. 问题本质（老办法套新问题）

多智能体结构是 **有根（或多根）的 N 叉树**（或森林）：

- **结点**：`agent_id`（canonical：`name@team`），全局唯一。
- **边**：`parent_agent_id` → 子结点列表 `children`。
- **变更操作**（经典树操作）：插入子结点、删除子树、重设父结点（reparent）、状态更新（running / finished 等）。

**新问题**：多个 **独立 OS 进程**（main、子 agent 子进程等）都能发起「加孩子」等操作；**老办法**仍是：

1. **单一事实来源（SoT）**：所有拓扑变更进入 **一条有序、只可追加的日志**（或等价结构）。
2. **纯函数式物化**：任意时刻的全局树 = `fold(初始空树, 日志序列)`，与「谁在哪个进程写的」无关。
3. **读者**（任意进程、任意 agent、Web console）只读 SoT + 同一套投影规则，得到 **一致视图**。

当前代码里，SoT 的载体主要是 **`get_data_dir() / "swarm" / "events.jsonl"`** 上的 `SwarmEvent` 流；物化入口是 **`SwarmProjection` + `RuntimeGraph`**。

---

## 2. 目标（验收口径）

无论拓扑从 **哪一入口** 被修改（main REPL、子 agent 内 `agent` 工具、Web console、`AgentManager` 合成场景等）：

| 能力 | 说明 |
|------|------|
| **全局 overview** | 任意读者能拿到与「全事件重放」一致的树（或经同一过滤器后的树，如 live reconcile）。 |
| **结点定位** | 给定 `agent_id`，能确定 **parent、children、lineage_path、root**（与投影一致）。 |
| **身份唯一** | 同一 `agent_id` 不静默覆盖；冲突时显式策略（错误 / 自动后缀，已有部分在 `AgentTool`）。 |
| **与任务层解耦** | **Swarm 拓扑** ≠ **BackgroundTaskManager**；任务可见性以 `tasks/*.json` + 约定为准（已有 `get_task`/`list_tasks` 读盘合并）。 |

---

## 3. 现象与已识别缺口

### 3.1 拓扑层（Swarm）

| 现象 | 可能原因 | 备注 |
|------|----------|------|
| 不同进程「看到的树」不一致 | 子进程 `TREECODE_DATA_DIR` 与 leader 不一致，写到另一套目录 | **环境约定**，非算法 |
| 极端情况下事件文件损坏或交错 | 多进程无锁 **append** 同一 `events.jsonl` | 需 **写入策略**（锁 / 单写者 / 分段文件） |
| Agent 难以自述「我在全局树哪」 | 仅有 `metadata` 注入，无统一 **只读拓扑查询工具** | 产品/API 缺口 |
| Web console / debugger 与 CLI 子进程视图不一致 | `reconcile_live_runtime` 等 **过滤规则** 与纯事件树不同 | 需文档化「两种视图」或统一策略 |

### 3.2 任务层（Background tasks）

| 现象 | 原因 | 已做 / 待做 |
|------|------|----------------|
| `task_list` / `task_get` 在 main 看不到子进程创建的任务 | 各进程 `BackgroundTaskManager._tasks` 仅内存；磁盘 `tasks/*.json` 才是跨进程共享 | **已实现**：`get_task` / `list_tasks` 合并磁盘记录（见 `tasks/manager.py`） |
| `task_stop` / `write_to_task` 跨进程 | 需 PID 或本机信号；句柄不在另一进程 | 保持「元数据全局、控制面按 PID」的边界说明 |

### 3.3 身份与注册（Context）

| 现象 | 原因 | 已有缓解 |
|------|------|----------|
| 嵌套 spawn 同名覆盖 | 默认 `subagent_type` → 同一 `name@team` | **`AgentTool._allocate_unique_swarm_identity`** |

---

## 4. 当前实现速查（给实现者）

| 概念 | 路径（相对 `src/treecode/`） |
|------|--------------------------------|
| 全局事件追加 / 重载 | `swarm/event_store.py` → `get_event_store()`，`events.jsonl` |
| 事件 → 树 | `swarm/projections.py` `SwarmProjection`，`swarm/runtime_graph.py` `RuntimeGraph` |
| 上下文快照（按 `agent_id`） | `swarm/context_registry.py`，`swarm/contexts/*.json` |
| 创建边 / 结点（工具路径） | `tools/agent_tool.py`（`agent_spawned` 等） |
| 控制台聚合视图 | `swarm/debugger.py` `_projection_payload`、`_filter_live_tree` |
| 任务磁盘记录 | `tasks/manager.py`，`get_tasks_dir()/*.json` |

---

## 5. 计划修改方式（分阶段 TODO）

以下为 **建议顺序**；新对话可勾选实现。

### Phase A — 文档与不变量（低成本）

- [x] **A1** 在 `docs/10-多智能体协调.md` 写清：**拓扑 SoT = swarm 事件流**；**任务 SoT = tasks JSON + log**；二者不混用术语。
- [x] **A2** 明确 **「live 树」vs「纯事件树」**：`reconcile_live_runtime` 过滤掉已结束子 agent 时的语义，与「全局永远显示所有历史结点」并不相同；已在文档中按 `topology_view=live|raw_events` 标注。
- [x] **A3** 启动文档：子 agent 子进程 **必须** 与 leader 共享同一 `TREECODE_DATA_DIR`（或默认 home data），否则拓扑必然分裂。

### Phase B — 给 Agent 的「只读拓扑 API」（推荐优先实现）

- [x] **B1** 新增只读工具 `swarm_topology`：输入可选 `agent_id`（默认当前 `metadata.swarm_agent_id`），输出 JSON metadata：**全树概要** 或 **以某结点为根的子树** + **该结点的 parent / children / lineage**。
- [x] **B2** 实现只依赖 `get_event_store().all_events()` + 同一套 `SwarmProjection` / `RuntimeGraph` 物化逻辑；不再读取各进程私有内存树做拓扑判断。
- [x] **B3** 新工具与 `SwarmDebuggerService.snapshot()` 统一成显式参数 `view=live|raw_events`，Web console 也共享该语义。
- [x] **B4** 已补单元测试：覆盖 raw/live 视图、agent summary/global 输出、`swarm_context` 与 debugger 一致性，以及 WebSocket 切换视图。

### Phase C — 写入路径健壮性（中风险，需评审）

- [x] **C1** 评估 `events.jsonl` **多进程并发 append**：首轮采用 `fcntl` 文件锁；`single-writer leader relay` 继续保留为后续增强方向。
  - 当前实现决策：**首轮先落 `fcntl` 文件锁**，保持 `EventStore -> SwarmProjection` 架构不变；`single-writer leader relay` 作为后续增强继续保留。
- [x] **C2** 已定义当前行为：POSIX 使用 `fcntl` 共享锁/独占锁；无超时控制，非 POSIX 平台退化为 no-op，后续若要强化再补平台专测。
- [x] **C3** 当前策略保持与 `AgentTool` 一致：优先通过唯一化 `agent_id` 避免重复 `agent_spawned` 冲突，不在 `EventStore` 读路径上做隐式合并。

### Phase D — 可选增强

- [ ] **D1** 轻量 **拓扑版本号** 或 **最后事件 id** 暴露给前端/WebSocket，便于 diff 而非全量 snapshot（与现有 `snapshot_revision` 关系理清）。
- [ ] **D2** `swarm_whereami`：仅返回当前 agent 一行摘要（parent、children、root），减少 token。

### Phase E — 任务层（若需回滚或收紧）

- [ ] **E1** 若团队决定 **task_list 仅本进程**：恢复严格内存语义，另增 `task_list_global` 读盘；**当前实现为合并磁盘**，改前需再确认产品意图。

---

## 6. 非目标（本清单不解决）

- 跨机器分布式一致树（多 host）；当前假设 **共享文件系统或单节点**。
- 在不做锁的情况下 **强保证** 并发 append 永不坏文件（需 C 阶段）。
- 用任务树替代 swarm 树，或合并两种模型。

---

## 7. 新对话起手式（可复制）

```
请阅读 docs/swarm-topology-global-visibility-todo.md，
从 Phase B 开始实现（或从 Phase A/C 中我指定的条目），
保持拓扑物化只走 EventStore + SwarmProjection，并补测试。
```

---

## 8. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-07 | 初稿：问题本质、目标、现象、分阶段 TODO |
