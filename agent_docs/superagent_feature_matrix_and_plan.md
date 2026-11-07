# Sunday Super-agent：完整功能覆盖清单与按依赖排序的执行计划

> 配套审查证据见 `agent_docs/superagent_reliability_audit.md`。
> 本文件同时是实施跟踪表：每项完成必须附“变更文件 + 可运行命令 + 实际结果 + 未完成项 + 回退方法”。
> **未运行过的项目一律标 Not run，不得打勾。**

状态图例：
- `已具备` 现网代码已正确实现并有测试，直接复用
- `待修复` 已复现失败，必须修
- `待新建` 仓库里没有，需要新增
- `受阻` 依赖前序步骤
- `不适用` 当前能力边界内不存在

---

## 1. 完整功能覆盖清单

### A1 基线 / 测试基础

| 项 | 状态 | 证据 / 说明 |
|---|---|---|
| 获取本地 HEAD 并复核设计包结论 | `已具备` | HEAD 39dd5c26；5 项成立、1 项已修复、0 误报 |
| 读取 AGENTS.md / 架构 / 迁移规范 / 现有 Skill | `已具备` | wishwright-skills 的 `wish-understanding` 已加载 |
| 为 6 项风险写修复前失败用例（含真实 DB store 语义） | `已具备` | `test_arrange_reliability_gate.py` 8 例全失败；并发与 fence 两例额外做了防假通过校验 |
| 只读备份 / 迁移幂等验证 | `待新建` | 沿用 `_LATE_COLUMNS` + `_ensure_late_columns`，配“旧库打开 + 二次启动零变更”用例 |
| 每次变更写明用户可见行为与回退 | `待新建` | 见第 7 节模板 |

### A2 Arrange 调度安全

| 项 | 状态 | 说明 |
|---|---|---|
| `max_active_jobs` 与 `claim_batch_limit` 分开 | `待修复` | 已复现峰值 16；`run_due_once` 不扣减活跃数 |
| 任意入口共用容量核算 | `待修复` | 只有 `run_due_once` 一个领取口，改造点集中，无需新调度器 |
| 单实例运行保护 | `待新建` | 无进程级互斥；`file_lock.py` 的写入期锁需改造为生命周期锁 |
| 队列公平性 `next_run_at, created_at, id` | `已具备` | `arrange.py:381`、`core_db.py:1651` 已有该排序 |
| 每次 claim 生成唯一执行标识 + 递增代际 | `待修复` | `fencing_token` 已有；缺随机 `execution_id` 用于审计串联 |
| 旧执行不能覆盖新执行 | `待修复` | 已复现：`_active_fences` 按 job_id 覆盖导致旧执行通过 fence 写检查点 |
| 同 occurrence 可安全重试 | `已具备` | `test_expired_lease_is_reclaimed_with_same_occurrence` 通过 |
| running `pause` 不落 cancelled | `待修复` | 已复现：暂停请求报 “Arrange job is terminal”，任务已取消 |
| `cancel` 幂等、保留意图 | `已具备` | `test_arrange_cancel_is_idempotent`、`test_runner_cancel_persists_cancelled_status` 通过 |
| 完成与暂停/取消竞争只有一个结果 | `待修复` | 需原子 `request_interrupt` 落库后再中断执行 |
| 定时 / 间隔 / 事件 / 日历 / 夏令时不退化 | `已具备` | `test_daily_calendar_job_keeps_local_wall_clock_time`、月度用例通过 |
| 重试区分暂时与永久失败、带 jitter | `待修复` | 当前 `fail_run` 固定 3 次、无 jitter、不区分错误类型 |
| 关闭与重启无残留锁 / 重复调度 | `待修复` | `_active_tasks` 按 job_id 覆盖，旧执行变孤儿；`stop()` 收不到 |
| 队列深度 / 运行数 / 最久等待 / 续租失败计数 | `待新建` | 无任何指标面 |

### A3 SQLite / 任务持久化

| 项 | 状态 | 说明 |
|---|---|---|
| 增量迁移、旧库可开、空库可起 | `已具备` | `create_all` + `_LATE_COLUMNS` + `_ensure_late_columns` 幂等 |
| 版本门控迁移有回归测试 | `待新建` | `_migrate_core_app_schema` 无用例；不得在其中加非幂等语句 |
| 信号 + occurrence 原子写入 | `已具备` | `core_db.py:2006` 单事务内完成 |
| 稳定 ID 唯一、重复不重复入队 | `已具备` | `db.get(CoreArrangeSignal, event_id)` 去重；observer 侧 `_bound_event_id` 稳定化 |
| 完成/重试/取消依赖 DB CAS | `已具备` | fencing_token + revision CAS 已落地 |
| 中断指令与租约状态事务一致 | `待修复` | 当前中断是“先取消执行协程、再改库”，非原子 |
| WAL / busy / recovery 单测 | `已具备` | `test_sqlite_write_pragmas.py`、`sqlite_write.py` 有退避与上限 |
| 返回可追踪 `job_id/occurrence_id/execution_id` | `待修复` | 缺 `execution_id` |
| 事件 / 尝试记录归档策略 | `待新建` | 无清理与归档 |

### A4 Observer / 事件可靠性

| 项 | 状态 | 说明 |
|---|---|---|
| v1 协议保留、标注 best-effort | `已具备` | `OBSERVER_PROTOCOL = "lamtools.signal.v1"` |
| v2 持久 spool + 提交后 ACK | `待新建` | `stdin=DEVNULL`，无回执通道 |
| 重启回放未 ACK 事件 | `待新建` | 已复现瞬时写库失败即永久丢事件 |
| 同 ID 同内容幂等、异内容报冲突 | `待修复` | 去重已有，但冲突检测缺失（当前直接返回既有记录） |
| `on-failure` 正常退出不重启 | `待修复` | 已复现 1.5 秒重启 24 次 |
| `always` 带指数退避 | `已具备` | `_schedule_restart` 有 2^n 上限 60s；需补 jitter 与持久化 |
| 超大 JSONL / 非法 UTF-8 / 背压不永久失效 | `待修复` | 已复现：超 1MB 行杀死读取任务，`len(line)` 分支是死代码 |
| 关闭后无残留子进程 | `待修复` | 无进程组管理，孙进程收不到 terminate |
| SHA256 内容批准仍有效 | `已具备` | `_resolve_approved_entry` + `test_observer_requires_new_approval_after_script_changes` |
| 只传白名单环境变量 | `已具备` | `subprocess_env()` + 显式注入项；需复核是否泄漏密钥 |
| `observer.status/rearm` | `待新建` | 只有内存态 `status()`，无 rearm，重启即丢 |

### A5 Health / 自愈 / 审计

| 项 | 状态 | 说明 |
|---|---|---|
| 调度循环受守护、临时 DB 故障可恢复 | `待修复` | 已复现一次 locked 即永久停摆 |
| 健康区分 ready / degraded / failed | `待修复` | `/api/health` 静态 `status: ok` |
| 连续异常可见（重试计数 / 最近出错 / 死任务数） | `待新建` | 无 |
| 崩溃后 1 个租约窗口内重新认领 | `已具备` | `recover_running` + `claim_due` 过期回收；需补“活 Worker 不被抢”用例 |
| Signal → Occurrence → Attempt → Effect → Report 串联 | `待新建` | 缺 effect 层 |
| 日志屏蔽密钥、可导出诊断包 | `待新建` | 无 |

### A6 执行权限 / 工作区隔离

| 项 | 状态 | 说明 |
|---|---|---|
| 只允许验证过的来源 / actor / repo 触发 | `待新建` | 无 source 层 |
| Policy 由宿主持有、外部文本不能扩权 | `待新建` | 现有 `ApprovalGate` 可作为硬闸门，但无 policy 层 |
| 最小权限 Mandate（repo / 路径 / 工具 / 分支 / 动作） | `待新建` | `sub_agent_runner` 的 work_root + 白名单可作底座 |
| 每 Ticket 唯一 worktree + 分支 + Session | `待新建` | 无 worktree 能力；`git_tools.py:37` 只有 status/diff |
| 执行前检查 Lease / Mandate / 批准级别 | `待新建` | `CoreToolbox.prepare_call` (`default_toolbox.py:1711`) 是唯一收口，可挂 |
| 禁止未授权目录与受保护分支 | `待新建` | 同上 |
| 超时 / 停止 / 退出后子进程退出 | `待修复` | `to_thread` 无法终止同步副作用；observer 无进程组 |
| 子 Agent 继承权限上限、不因换模型扩权 | `已具备` | 白名单与等级上限由构造器注入，模型 schema 无法改 |

### A7 Super-agent 上层

| 项 | 状态 |
|---|---|
| GitHub source adapter（Issue/PR/comment/CI）+ cursor 重放 | `待新建` |
| Eval（接单 / 忽略 / 待人工）+ policy 版本入库 | `待新建` |
| Ticket 生命周期独立于 Arrange | `待新建` |
| 同事件重复投递只建一张 Ticket | `待新建`（可直接复用 event_id 去重） |
| Assignment 绑定 Worker Session / 目录 / 租约 / Report | `待新建` |
| 追问不扩权 | `待新建` |
| Worker 自测 + 可审查补丁 | `待新建` |
| 结果 Outbox 可重试可核对、超时不重复建 PR | `待新建` |
| CLI 审阅 / approve / reject / stop / retry | `待新建` |
| 无权限与失败给出可行动解释 | `待新建` |

### A8 发布 / 回退 / 兼容

| 项 | 状态 |
|---|---|
| 旧 Session / Goal / Arrange / Checkpoint 可用 | `待验证`（需双版本打开测试） |
| 用 Tauri 与现有 CLI 验收，不用浏览器截图代替 | `待执行` |
| DB 备份与 schema 回退预案 | `待新建` |
| 关闭开关可退回老逻辑（安全修复除外） | `待新建` |
| 安全检查纳入 CI | `待新建` |
| 文档与 UI 说明真实限制 | `待执行` |

---

## 2. 按依赖排序的执行计划

| 步 | 内容 | 前置 | 交付物 | 最早可运行验证 | 完成标准 |
|---|---|---|---|---|---|
| 0 | 复核与复现 | 无 | 本两份文档 + 8 例失败测试 | 已达成 | 每一项都有失败证据，无凭空结论 |
| 1 | 暂停不再变取消 | 0 | `request_interrupt(job_id, target)` 原子落库；先改状态再中断执行 | 一个 running 任务 pause → 落 `paused`，旧执行被拒 | 0 次误取消；暂停先提交则旧结果被 fence；恢复后按 occurrence 规则继续 |
| 2 | 总并发上限 + 单实例 | 0 | `max_active_jobs` / `claim_batch_limit` 分离 + 进程生命周期锁 | 1000 任务、并发 3，峰值恒 ≤3 且队列排空 | 峰值从不超限；任意入口共用核算；第二个宿主进程启动即拒绝并给出原因 |
| 3 | fencing 残留修补 | 1,2 | 每次领取随机 `execution_id`；活跃执行按 execution 记账而非 job_id | 旧执行 checkpoint/complete 全部被拒 | 0 次过期执行越权；旧执行不再变孤儿，`stop()` 能收全部 |
| 4 | 循环自愈 + 健康 | 2,3 | 循环级异常边界 + 指数退避 + `arrange.health` / `observer.health` + 统一后台台账 | 注入一次 `database is locked`，10 秒内自愈 | ready/degraded/failed 可区分；死循环可被 health 读出；无需重启进程 |
| 5 | Observer 生命周期 | 0,4 | 持久 `observer_lifecycle`（desired_state / last_exit_code / last_exit_reason / restart_count / next_retry_at）+ `observer.rearm` | `on-failure` + exit 0 后不再重启；`always` 退避重启 | 正常退出终态跨进程重启仍生效；rearm 生效；无热循环 |
| 6 | Observer v2 ACK 投递 | 3,5 | v2 协议 + spool + 提交后 ACK + 连续游标推进 + 冲突检测 | 强杀任意点重启后事件不丢 | 0 次已 ACK 事件丢失；重复投递只 1 条 occurrence；同 ID 异内容报冲突 |
| 7 | 脏输入与子进程卫生 | 4 | 超长行有界读取、非法 UTF-8 容错、进程组强杀 | 超 1MB 行之后合法事件仍被处理 | 无残留子进程；读取循环不因单行脏数据失效 |
| 8 | 副作用幂等 | 3,6 | `outbox_effects`（`idempotency_key` UNIQUE）+ 远端 lookup 补偿 | 模拟远端超时后重试 | 不重复创建外部资源；超时先查后建 |
| 9 | 隔离 Worker | 3,8 | `git worktree` 执行器 + 分支命名 + 清理 + 与 Session 绑定 | 两 Ticket 并发改不同分支 | 工作树不交叉；失败可回滚；不污染主工作区 |
| 10 | Source / Policy / Eval | 6,9 | GitHub adapter + 宿主持有的 policy 硬闸门 + Eval 决策入库 | CLI 模拟事件 | 未授权事件绝不执行；模型输出不能扩权 |
| 11 | Ticket / Assignment | 8,9,10 | 工单表与状态机 + assignment 绑定 + 追问路由 | 同 Ticket 多事件复用 | 状态可解释可恢复；追问不扩权 |
| 12 | FMVP 端到端 | 11 | Issue → Eval → Ticket → Worker → 测试 → 待审补丁 | 临时仓库跑通一条链 | 无人工干预只做授权范围内动作 |
| 13 | 最简 UI + 长期运行 | 12 | 状态面板（只消费 CLI/RPC）+ 诊断包 + 24h soak | Tauri 内查看状态 | 4.6 / 4.7 达标或明确标注未达标 |

### 2.1 关键路径

```
0 →（1 并发 2）→ 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13
```

- 1 与 2 可并行，但 3 必须把两者的并发写入一起纳入 fence 语义。
- 5 必须先落持久终态，6 的 ACK 才有意义（否则重启后无从判断该不该拉起）。
- 8 必须在任何真实外部写操作之前完成，不能靠“PR 提交成功”倒逼幂等设计。
- **最早可交付价值：完成 1–4，Sunday 的安排任务就已稳定可停止、可恢复，不必等 Super-agent 做完。**
- 7 可与 8 并行，属于 A4 收尾但需在 6 之后以免返工。

### 2.2 每个步骤的完成定义（DoD）

1. 有修复前失败用例，且修复后同一用例通过（同一文件、同一断言，不放宽）。
2. 相关后端测试无回归；不能运行时明确写 Not run。
3. 公共接口与历史数据兼容，迁移可重复运行。
4. 有日志 / 指标能定位失败原因。
5. 交付 `变更文件 + 可运行命令 + 实际结果 + 未完成项 + 回退方法`。
6. 涉及远端写入、合并、发布，只在明确授权后执行。

---

## 3. 量化验收对照

| 验收 | 指标 | 当前真实状态 | 达成步骤 | 验证方式 |
|---|---|---|---|---|
| 4.1 | 1000 任务 / 并发 3，峰值 ≤3 且排空 | **不达标**：无并发配置项，实测峰值 16（5 轮 × 10） | 2 | `test_peak_concurrency_never_exceeds_configured_limit` 扩到 1000 任务 |
| 4.2 | 0 次暂停误取消、0 次过期执行越权 | **不达标**：误取消 100%；旧执行可写检查点 | 1, 3 | 两个复现用例转绿 + 完成/暂停竞争用例 |
| 4.3 | 同事件 100 次只处理一次 | **部分达标**：DB 去重已成立；Observer 侧无 ACK | 6 | 100 次重复投递用例 + 强杀重放用例 |
| 4.4 | 0 次已 ACK 事件丢失 | **不适用**：无 ACK 机制 | 6 | 8 个断点强杀矩阵 |
| 4.5 | 正常退出不重启、故障按策略恢复、DB 短暂故障不停摆 | **不达标**：24 次重启 / 一次 locked 即停摆 | 4, 5 | 三个复现用例转绿 |
| 4.6 | 24h soak + 100 次随机崩溃恢复 | **Not run** | 13 | 隔离环境长跑脚本 |
| 4.7 | 空闲槽调度延迟 p95 ≤2s | **Not measured**（默认 poll 1s，量级可行） | 2, 4 | 埋点计时，报告 p50/p95 |
| 4.8 | 未授权写拒绝、PR 不重复 | **部分达标**：审批闸门已有；无 PR 能力；无单实例锁 | 2, 8, 10 | 未授权事件用例 + 超时重试用例 |

---

## 4. 风险

1. **暂停语义的期望落差**：通用 shell / 外部 API 无法做“CPU 级冻结”。暂停只能定义为“停止当前执行、保留可恢复状态，恢复时先核验再续做”。若要求原位无损续跑，需要单独的进程级 checkpoint 机制，成本远高于本方案。
2. **取消的真实性**：`asyncio.to_thread` 无法终止已进入同步代码的副作用。要真正可停止，必须把执行放进受管进程/进程组。这会影响 `execute_arranged_job` 的调用方式，属较大改动，需在步骤 3 一并评估。
3. **单实例锁的副作用**：Tauri 桌面、CLI、`desktop_backend.py` 可能同时启动后端。加锁前必须确认现有启动路径，否则会把正常用法锁死。
4. **Observer v2 协议迁移**：现存用户脚本都是 v1。v2 必须能识别 v1 并降级为 best-effort，不能直接拒绝。
5. **版本门控迁移无测试**：`_migrate_core_app_schema` 是一次性语义，一旦加入非幂等语句，升级失败的库永久卡住。新增字段一律走 `_LATE_COLUMNS`。
6. **审计子代理无法执行命令**：两轮子代理均被只读级别拦截，其中“命令示例需自行推导”的部分（CLI 用法）我已在主会话核对 `parser.py` / `parse_workspace.py`，但未实际运行 CLI 命令，标为未验证。
7. **工作区脏**：当前分支有大量未提交的桌宠改动。所有实现必须在 `sunday/` 前缀分支上做，不碰这些改动。

---

## 5. 回退方案

- **代码**：每一步单独提交，按步骤可单独 revert；`max_active_jobs` 等新配置全部有安全默认值（缺省保持现有行为），关闭即退回老逻辑（安全修复项除外）。
- **数据库**：新增列走 `_LATE_COLUMNS`（只增不删，旧版本读到多余列不影响）；新增表由 `create_all` 建，旧版本忽略。回退只需回滚代码，不回滚 schema。
- **备份**：动 schema 前对 `data/core.db` 做一次只读副本，记录恢复命令。
- **Observer**：v2 上线后保留 v1 入口；配置项可切回 v1。

---

## 6. 需要用户确认的决策

| # | 决策 | 选项 | 我的判断依据 |
|---|---|---|---|
| D1 | 是否先只做 1–4（底座），确认稳定后再做 Super-agent 上层 | A. 只做 1–4 交付确认<br>B. 1–4 完成即继续 5–7<br>C. 一路做到 12 | 设计包 F 明确“禁止先做上层再补底座”；1–4 完成后 Sunday 已经可停止可恢复，是最高性价比的节点 |
| D2 | 暂停的可接受语义 | A. 停止执行 + 保留可恢复状态（不承诺原位续跑）<br>B. 要求进程级冻结与原位续跑 | B 需要重做执行器为受管进程，工期与风险显著上升；A 与现有架构一致 |
| D3 | 并发上限的默认值 | A. 4（与现有 claim_limit 一致）<br>B. 3（贴合验收 4.1）<br>C. 由配置决定，默认 3 | 验收按 3 压测；默认值只影响开箱体验 |
| D4 | 单实例锁的作用范围 | A. 只锁 core 后端进程<br>B. 锁整个应用（含 Tauri 多窗口）<br>C. 先不加锁，仅记录告警 | 需要先确认桌面端是否会有多个后端实例；先加锁可能误伤正常启动路径 |
| D5 | Observer v2 是否强制 | A. v2 为默认，v1 保留 best-effort<br>B. 只做 v1 加固 + 明确标注不保证 | 4.4 的验收要求 ACK，选 B 则 4.4 永久 Not run |
| D6 | 实现分支 | A. 用现成的 `sunday/self-dev-runtime` 工作树（`E:/LamTools/.worktrees/self-dev`，已在 39dd5c26）<br>B. 另开 `sunday/reliable-base`<br>C. 直接在当前 `codex/plugin-market-0.3.23` | 当前分支有大量未提交桌宠改动，直接开发会混入无关变更；`sunday/` 前缀是项目既定约定 |
| D7 | 是否允许我在隔离工作树里先实现步骤 1–2 作为可运行原型 | A. 允许，合入前再确认<br>B. 只交付计划，代码等确认后再写 | 3.3 要求“获得明确认可后再修改正式代码”；隔离工作树不等于正式代码 |

---

## 6.1 实施结果（2026-11-02 更新）

用户选择"一路做到 12 步"，已在 `sunday/reliable-base` 分支（工作树 `E:/LamTools/.worktrees/reliable-base`，提交 62becca4）实施完成，未 push。

| 步 | 状态 | 证据 |
|---|---|---|
| 1 暂停 | 完成 | `test_pausing_a_running_job_keeps_it_paused` |
| 2 并发 + 单实例 | 完成 | 1000 任务实测峰值 3；`test_scheduler_lease_allows_only_one_holder` |
| 3 fencing | 完成 | `test_stale_execution_cannot_write_checkpoint_of_new_execution` |
| 4 自愈 + 健康 | 完成 | 注入一次 locked 后自动恢复 |
| 5 生命周期 | 完成 | 跨进程重启不再自动拉起 |
| 6 ACK | 完成 | v2 提交后回 ACK，丢弃后重发被去重 |
| 7 脏输入 | 完成 | 1.5MB 行之后合法事件仍被处理 |
| 8 幂等副作用 | 完成 | 超时不重复建 PR |
| 9 隔离 worktree | 完成 | 两工单不同目录不同分支 |
| 10 Source/Policy/Eval | 完成 | 未授权一律拒绝（默认拒绝） |
| 11 Ticket/Assignment | 完成 | 同事件 100 次 → 1 张工单 |
| 12 FMVP + CLI | 部分 | CLI 可用；Tauri 面板未做 |

实测指标：调度延迟 p50 5.0ms / p95 8.1ms（目标 ≤2s）；1000 任务容量 3 峰值 3 且全部完成。
未验证：24 小时 soak 与 100 次崩溃恢复（脚本已就绪：`core/scripts/arrange_soak.py`）。
完整报告：`agent_docs/superagent_implementation_report.md`。

## 7. 每步交付模板

```text
步骤：<编号与名称>
变更文件：<逐项路径>
关键实现：<函数 / 事务边界 / 状态机改动>
修复前：<命令 + 失败输出摘要>
修复后：<命令 + 通过输出摘要>
回归：<命令 + 通过/失败数>
兼容性：<旧库打开 / 迁移幂等 / 接口不变>
未完成：<明确列出，没有就写"无">
回退：<revert 步骤 / 配置开关 / DB 处理>
```
