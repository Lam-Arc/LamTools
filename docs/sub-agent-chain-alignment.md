# Sub Agent 链路与主 Agent 链路对齐 —— 梳理备忘

> 状态：**暂缓执行**（2026-08-09 备忘）。本文件为调查结论固化，Phase B 代码改动待另行确认后实施。

## 背景

代码审查发现 sub agent 链路与主 agent 链路存在若干不一致。本文档固化全部核实结论（含源码证据），并给出修复方案与明确的"不修"决策。

## 全景：两条链路共用管线

```
[CoreLoopKernel] --emit CoreEvent--> CollectingEventSink
                                     ├─ core_events_to_run_items() 投影为 RunItemEvent（"节点"事实）
                                     └─ live: _persist_core_event_live() 实时落库 + hub.publish
[App 事件表] SqlAlchemyAppEventStore (per-thread seq 单调分配) → AppEventEnvelope
[快照] SqlAlchemyThreadSnapshotStore → CoreAppSnapshotProjector / snapshot reducer
[出口] live_router WebSocket /app-server（JSON-RPC）+ event 流（hub 队列）
```

子代理跑的是**同一个 `CoreLoopKernel`**（`tool/sub_agent_runner.py:_build_kernel`），事件经
`SubAgentEventForwardingSink`（`src/lamtools_core/sub_agent.py:6-59`）转发进主代理的同一 sink——
**session/run/turn 重父级化**（`source="sub_agent"`，真实子 run_id 存 `payload.sub_agent.run_id`），
下游投影、落库、快照、UI 全部共用。因此不一致是少数几处的**行为分叉**，不是两套管线。

## 已核实的不一致清单（10 项 → 5 项待修 / 5 项关闭）

| # | 项目 | 证据 | 结论 |
|---|------|------|------|
| 1 | 子代理终态节点被吞（done/failed/cancelled 投影返回 []） | `event/runtime_projection.py:590-594` | **修（P0）** |
| 2 | 子 kernel `cancel_event_source=None`，turn.cancel 无法中断子代理 | `kernel/loop.py:228-230` | **修（P0）** |
| 3 | 完成态 sub-line 正文依赖父节点拼装，失败时显示合成文本 "SUB_AGENT FAILED" | `ui/src/components/MessageView.vue:3108-3127` | **修（P0）** |
| 4 | 快照水合守卫不比较 `core.items` 删除 → 回退截断后不重连的宿主显示旧节点 | `ui/src/appServer/store.ts:662-744` | **修（P1）** |
| 5 | 死代码 `agents/subAgentProjection.ts` / `CoreSubAgentPanel.vue` / `CoreSubAgentDialog.vue`（仅 index.ts 导出，无消费） | `ui/src/index.ts:95,103-104` | **修（P1）** |
| 6 | 子代理 usage/metrics 合入父 turn，不区分代理 | `event/runtime_projection.py:399-425` | **修（P2，可选）** |
| 7 | 审批 wait 不可见 | `event/runtime_projection.py:427-430` | **关闭**：对主/子同样丢弃，行为一致 |
| 8 | 子工具 item_id 与父节点碰撞风险 | `event/runtime_projection.py:754-758` + `kernel/loop.py:89` | **关闭**：call_id=uuid4，碰撞可忽略，仅补注释 |
| 9 | 子代理消息级回退不可达 | `MessageView.vue:2197-2202`、`ui/src/demo/App.vue:1401-1417` | **关闭**：用户明确不需要 |
| 10 | 嵌套子消息走 live 分支、主代理走 history 分支 | `MessageView.vue:1753-1783` | **关闭**：live 紧凑展示为设计；操作按钮与 #9 一并排除 |

## 关键机制事实（修复方案的设计依据）

- **终态判定**：主代理 `runtime.done/failed/cancelled` 投影为 `{run_id}:terminal` status 节点
  （`runtime_projection.py:596-625`）；子代理同类事件被吞（:590-594，注释：
  "The parent sub_agent tool result owns the delegated run's visible terminal state"）。
- **reducer 风险**：`snapshot/__init__.py:56-80` kind==status 分支会把任意 status 事件直接改写
  `state["status"]` / `turn["status"]` 并 `_close_turn_items` —— 若子代理终态照搬主代理投影，
  会用子状态污染父 turn。**这是现状"吞掉"的根因**，修复必须用 payload 标记隔离。
- **取消机制**：主 kernel `cancel_event_source` 来自 RuntimeTaskRegistry（`loop.py:224-230`，
  live 路径 `turn.cancel` 设置），子 kernel 显式传 None（:230 注释 "None for sub-agent kernels"）。
  父 kernel 在 await 工具执行期间无法自行轮询取消，子代理必须共享同一个 cancel event。
- **call_id 生成**：`loop.py:89` `uuid.uuid4().hex[:12]`，跨 kernel 碰撞概率可忽略。
- **子工具节点 id**：`{thread}:{parent_run}:{child_call}:tool`（`runtime_projection.py:754-758`），
  scope 是父 run —— 与主代理节点区分靠 call_id 唯一性（见上）。
- **审批可见性**：`runtime.waiting` kind=="permission" 投影返回 []（:427-430）对主/子一视同仁；
  审批请求本身经 `runtime.approval_request`（kind=approval_request）可见，子代理同样转发投影。
- **usage**：子代理 usage 事件 turn_id=父 turn（转发时重父级化），合并进父 turn usage 字段。

## Phase A（已完成）

本文档即 Phase A 产物。

## Phase B 方案摘要（待确认后实施）

### P0-1 子代理终态节点投影（后端核心）
- `event/runtime_projection.py:590-594`：不再吞掉，改为投影 `kind="status"` 子节点：
  - `item_id = f"{sub_agent['run_id']}:terminal"`（真实子 run，避免与父 `{父run}:terminal` 冲突）；
  - `parent_item_id = 父 sub_agent 工具节点`（复用 `_sub_agent_parent_item_id`）；
  - `payload = {"type": "sub_agent", "status": completed/failed/cancelled, "agent", "message", "raw_end_reason"}`。
- `snapshot/__init__.py:56-80` kind==status 分支：`payload.type == "sub_agent"` 时
  **只 upsert item + last_error，跳过 turn/thread 状态改写与 `_close_turn_items`**；其余行为不变。
- 效果：子代理失败/取消在快照与 UI 有就地终态节点；父 turn 生命周期不受影响。

### P0-2 取消信号贯通（后端）
- 父 kernel 构造后把 `cancel_event_source` 注入 `CoreToolbox`（新属性，默认 None 兼容）；
- `call_sub_agent`（`tool/default_toolbox.py:1061-1192`）读取并传给
  `KernelSubAgentRunner.run` 新参数；`sub_agent_runner.py:_build_kernel` 透传给子 kernel（`loop.py:230`）。
- 效果：`turn.cancel` / `turn.force_reset` 通过共享 event 协作式中断运行中的子代理；
  中断后经 `_result_from_kernel` 映射为 cancelled 结果返回父代理。

### P0-3 完成态 sub-line 正文来源对齐（前端）
- `MessageView.vue:3108-3127` `agentConclusion()` completed 分支：优先 `latestSubLineModelText(part)`
  （子代理自身最终 model_text，与 running 分支同源），再回退 `toolResult`/`content`；
  error/failed/cancelled 时展示 P0-1 终态节点 message + 失败样式。
- 效果：不再"运行中可见、完成后变空/变合成文本"。

### P1-4 快照水合守卫补删除检测（前端）
- `store.ts:662-744` `shouldHydrateSnapshot`：增加 `core.item_order`（或 ids 指纹）新旧比较，
  回退截断/节点删除导致 item_order 缩短时强制水合；只在 snapshot 消息时比较一次，不引入每帧成本。

### P1-5 死代码清理（前端）
- 删除 `ui/src/agents/subAgentProjection.ts`、`CoreSubAgentPanel.vue`、`CoreSubAgentDialog.vue`、
  `index.ts` 对应导出；先 grep 确认测试引用范围并同步清理（当前仓库仅 index.ts 导出）。

### P2-6 usage 按代理拆分（可选）
- reducer usage 合并处：`metadata.sub_agent.run_id` 存在时归入 `turn.usage.sub_agents[run_id]`，
  主 usage 保持原字段；UI 不新增展示，仅数据保真。

## 明确不做（记录理由）

- 子代理消息级回退 / checkpoint 图回退（用户确认不需要）。
- 嵌套子消息操作按钮（live 分支紧凑展示为设计，随 #9 排除）。
- 审批 wait 投影（主/子行为一致）。
- item_id 碰撞防护（uuid 碰撞可忽略，实现时在 `runtime_projection.py:754` 附近补注释说明）。

## 验证方式

- 后端：`pytest core/tests/test_runtime_projection.py core/tests/test_core_sub_agent_runner.py core/tests/test_snapshot*.py`
  （含现有 20 个 runner 用例回归）。
- 前端：`core/ui` 现有 vitest 测试全量回归 + 手测子代理运行→完成→失败→取消四条路径的 sub-line 表现。
