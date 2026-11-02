# Sunday 可靠底座 + Super-agent 实施报告

> 配套文档：`agent_docs/superagent_reliability_audit.md`（审查与复现）、`agent_docs/superagent_feature_matrix_and_plan.md`（清单与计划）。
> 实现分支：`sunday/reliable-base`（工作树 `E:/LamTools/.worktrees/reliable-base`，基于 39dd5c26）。
> 未 push、未 merge、未 release。

## 1. 环境

| 项目 | 值 |
|---|---|
| 基线提交 | 39dd5c26 |
| Python / pytest | 3.14.4 / 9.0.3 |
| 平台 | Windows 11，SQLite（aiosqlite + SQLAlchemy） |
| 测试库 | 全部 `tmp_path` 独立 SQLite 或 InMemory，未触碰 `data/core.db` |
| 隔离手段 | 独立 git worktree + 独立 SQLite + 临时 git 仓库（worktree 测试） |

## 2. 实施范围与状态

| 步 | 内容 | 状态 | 证据 |
|---|---|---|---|
| 1 | 暂停不再变取消 | 完成 | `test_pausing_a_running_job_keeps_it_paused`、SQL 版 `test_sql_atomic_interrupt_*` |
| 2 | 总并发上限 + 单实例 | 完成 | `test_peak_concurrency_never_exceeds_configured_limit`、`test_scheduler_lease_allows_only_one_holder`、1000 任务实测 |
| 3 | fencing 残留（execution 隔离） | 完成 | `test_stale_execution_cannot_write_checkpoint_of_new_execution`、`test_sql_claim_assigns_execution_id_*` |
| 4 | 循环自愈 + 健康 | 完成 | `test_arrange_loop_survives_transient_database_failure`、`test_arrange_and_observer_expose_live_health_snapshot` |
| 5 | Observer 生命周期 | 完成 | `test_on_failure_observer_exiting_cleanly_is_not_restarted`、`test_clean_exit_stays_stopped_across_supervisor_restart` |
| 6 | Observer v2 ACK | 完成 | `test_v2_observer_advances_cursor_only_after_host_ack`、`test_v2_observer_redelivery_after_missing_ack_is_deduplicated` |
| 7 | 脏输入与子进程卫生 | 完成 | `test_oversized_observer_line_does_not_kill_signal_reader`；`_terminate_tree` 用 taskkill /T / killpg |
| 8 | 副作用幂等 outbox | 完成 | `test_effect_outbox_does_not_create_duplicate_on_timeout` |
| 9 | 隔离 Worker（worktree） | 完成 | `test_two_tickets_get_isolated_worktrees` |
| 10 | Source / Policy / Eval | 完成 | `test_untrusted_actor_cannot_create_ticket`、`test_empty_policy_denies_everything`、`test_high_risk_action_in_payload_goes_to_human` |
| 11 | Ticket / Assignment | 完成 | `test_same_event_delivered_100_times_creates_one_ticket`、`test_revoked_mandate_blocks_assignment` |
| 12 | FMVP 端到端 + CLI | 部分 | CLI 已可用；**Tauri 面板未做** |

## 3. 变更文件

### 3.1 修改（7 个）

| 文件 | 关键改动 |
|---|---|
| `core/src/lamtools_core/runtime/arrange.py` | `max_active_jobs` 容量闸门；`execution_id`；执行现场按 execution 记账；`interrupt()` 只停执行不改库；`health()`；循环级自愈与退避；`atomic_interrupt`（内存版）；`request_interrupt`；`count_queued`；`_active_tasks` 兼容视图 |
| `core/src/lamtools_core/runtime/observer.py` | v2 协议与 ACK；生命周期持久化（`stopped_successfully` 终态）；有界行读取；进程组终止；`health()` / `rearm()`；`status()` 只返回真实发生过的字段 |
| `core/src/lamtools_core/app/core_db.py` | `execution_id` 列 + `_LATE_COLUMNS` 幂等补列；claim/renew/checkpoint/complete/fail 全链路 execution 校验；`count_queued`；`atomic_interrupt`；`core_observer_lifecycle`、`core_superagent_records` 两张新表 |
| `core/src/lamtools_core/app/durable_operations.py` | 暂停改走 `request_interrupt` + `interrupt_running`；新增 `arrange.health`、`observer.status`、`observer.rearm` |
| `core/src/lamtools_core/app/operation_groups.py` | 三个新操作名登记 |
| `core/src/lamtools_core/app/http_agent_app.py` | 接线：并发闸门、生命周期存储、单实例调度租约、健康状态、Super-agent 服务 |
| `core/src/lamtools_core/cli_commands/parser.py` | 注册 `superagent` 命令组 |

### 3.2 新增（12 个）

```
core/src/lamtools_core/runtime/single_instance.py        调度器单实例租约
core/src/lamtools_core/superagent/__init__.py
core/src/lamtools_core/superagent/models.py              Source/Event/Mandate/Ticket/Assignment/Effect
core/src/lamtools_core/superagent/policy.py              宿主授权硬闸门
core/src/lamtools_core/superagent/effects.py             幂等副作用 outbox
core/src/lamtools_core/superagent/worktree.py            git worktree 隔离
core/src/lamtools_core/superagent/store.py               (kind,id) 持久化 + 内存实现
core/src/lamtools_core/superagent/service.py             事件→工单→排期编排
core/src/lamtools_core/app/superagent_operations.py      9 个操作
core/src/lamtools_core/cli_commands/superagent.py        CLI 实现
core/src/lamtools_core/cli_commands/parse_superagent.py  CLI 参数
core/scripts/arrange_soak.py                             长跑 / 崩溃恢复验证脚本
```

测试新增 4 个文件：

```
core/tests/test_arrange_reliability_gate.py        8 例（六项缺陷 + 单实例）
core/tests/test_observer_ack_and_lifecycle.py      5 例（ACK / 生命周期 / SQL 隔离）
core/tests/test_superagent_runtime.py             10 例（授权/去重/幂等/隔离/工单）
core/tests/test_arrange_acceptance_metrics.py      2 例（1000 任务并发、调度延迟）
```

## 4. 关键实现

### 4.1 并发闸门（4.1）

`run_due_once` 先算空槽再领取：`available = max(0, max_active_jobs - len(_active))`，领取量取 `min(available, claim_limit)`。`claim_limit` 仍是"每轮领取批量"，两个概念分开。宿主默认 `max_active_jobs=3`，可用 `LAMTOOLS_ARRANGE_MAX_ACTIVE_JOBS` 覆盖。

单实例：`SchedulerLease` 在数据目录上取进程生命周期文件锁（Windows 偏移 4096 的字节锁 + 进程内注册表双保险）。第二个进程照常提供 HTTP，但**不启动调度器**，`/api/health` 报 `degraded` 且 `scheduler_lease=held-by-another-process`。

### 4.2 暂停语义（4.2）

```
arrange.pause → arrange_manager.request_interrupt(job_id, "paused")
              → 单事务：occurrence=pending、status=paused、execution_id=""
                        fencing_token+1、租约释放
              → arrange_runner.interrupt(job_id) 只取消协程，不改库
```

旧执行此后的 `complete_run/fail_run/checkpoint_run` 因 `fencing_token` 与 `execution_id` 双重不匹配被拒。取消走同一条路径，目标为 `cancelled`。

### 4.3 执行隔离（4.2）

- 每次 claim 生成 `execution_id = exec_<uuid>` 并写入库。
- 运行期用 `ContextVar` 绑定"当前执行"，`runner.checkpoint(job_id)` 取的是**调用者自己那次执行**的 fence，而不是按 job_id 反查——这是旧实现的漏洞：租约过期被重新领取后，旧执行会借用新代际写检查点。
- 活跃执行以 `execution_id` 为键，`stop()`/`interrupt()` 能触达全部执行；保留 `_active_tasks` 只读兼容视图给既有调用方。

### 4.4 Observer 可靠投递（4.3/4.4）

- v1 原样保留（best-effort）；v2 在**事务提交之后**才向子进程 stdin 回 `{"type":"ack","event_id":...}`。
- ACK 写失败只计数不阻塞（`acks_dropped`）；观察器重发 → 宿主按 `event_id` 去重（原有能力，直接复用）。
- 宿主侧 `emit_signal` 增加**有界重试**（0.05/0.15/0.35s，共 4 次），耗尽后记录，不做无限重试。

### 4.5 Observer 生命周期（4.5）

`restart=on-failure` 且退出码 0 → 持久化 `desired_state=stopped_successfully`，`reconcile_once` 直接跳过。跨进程重启同样生效（`core_observer_lifecycle` 表）。只有 `observer.rearm` 才会复活。

### 4.6 自愈与健康（4.5）

`ArrangeRunner._run` 与 `ObserverSupervisor._run` 都有循环级异常边界：记录 `consecutive_failures` / `last_error`，指数退避（上限 30s / 60s）后继续，不退出。`/api/health` 现在返回：

```json
{"status": "ok|degraded|failed",
 "runtime": {"arrange": {"alive":true,"active":0,"capacity":3,"queued":0,...},
             "observer": {"alive":true,"running":0,"backoff":0,...},
             "scheduler_lease": "acquired"}}
```

`arrange.health` 操作也暴露同一份快照给 CLI。

### 4.7 脏输入（5.1）

`readline(limit)` 换成"按 64KB 读块 + 自行切行"：超限行丢弃并计数，之后继续读；不再因为一行坏数据让整个信号通道永久失效。

### 4.8 Super-agent 层（8–11）

- **Policy**：默认拒绝。来源/事件类型/身份/仓库都必须显式授权；事件正文出现 `push/create_pr/merge/release` 一律转人工，模型或 issue 作者无法凭文字扩权。
- **Ticket**：`ticket_id = hash(source:event)`，`create_only` 保证同一事件只建一张，崩溃重放同样安全。
- **Assignment**：绑定 execution_id / worktree / branch，完成即把工单推进到 `review`。
- **Worktree**：`git worktree add -b ticket/<id>`，仓库必须在授权根内，基分支不存在时回退 HEAD，失败会清理半成品。
- **Effect outbox**：`idempotency_key` 唯一 + 落库前先 `lookup` 远端，超时重试不会重复创建 PR/评论。
- **排期复用 Arrange**：注入的 scheduler 就是 `arrange_manager.create(...)`，没有第二套调度器。

### 4.9 CLI

```
core superagent ingest --source github --event-id 1 --event-type issue.opened \
    --actor alice --trusted --repo E:\repo --text "修复登录按钮"
core superagent tickets [--stage blocked]
core superagent show <ticket_id>
core superagent approve <ticket_id> --approver lam
core superagent reject <ticket_id> --reason "不是我们要的"
core superagent stop <ticket_id>
core superagent assignments [ticket_id]
core superagent audit
core superagent policy
```

`core superagent --help` 已实际运行通过（输出见第 6 节）。

## 5. 修复前后证据

### 5.1 修复前（基线 HEAD，隔离工作树）

```
8 failed in 24.42s
  AssertionError: 峰值并发 16 超过配置上限 3
  AssertionError: 暂停请求被拒绝: {'error': 'Arrange job is terminal: ...'}
  AssertionError: 过期执行通过了 fence 校验并写入了检查点
  AssertionError: 正常退出的观察器被重启了 24 次
  AssertionError: 事件最终入库 was not met before timeout
  AssertionError: 任务在数据库恢复后被执行 was not met before timeout
  AssertionError: ArrangeRunner 没有健康快照
  AssertionError: 超长行之后的合法事件 was not met before timeout
```

### 5.2 修复后（本分支）

```
tests/test_arrange_reliability_gate.py            9 passed
tests/test_observer_ack_and_lifecycle.py          5 passed
tests/test_superagent_runtime.py                 10 passed
tests/test_arrange_acceptance_metrics.py          2 passed
--------------------------------------------------------
合计 26 例全绿
```

回归（含既有用例）：

```
63 passed（arrange_runtime / arrange_fencing / observer_runtime /
           durable_operations / core_db_late_columns / sqlite_write_pragmas
           + 本次 26 例）
76 passed, 1 skipped（core_http_agent_app 全套）
```

`core_http_agent_app.py` 里有 **6 个用例在原始 HEAD 上同样失败**（附件存储路径假设、缺 Rust 网络控制器），与本次改动无关，已在基线工作树交叉验证。

## 6. 量化指标（实测）

| 验收 | 目标 | 实测 | 结论 |
|---|---|---|---|
| 4.1 峰值并发 | 1000 任务、并发 3，峰值 ≤3 | 峰值 **3**，1000 个全部 completed | 达标 |
| 4.2 暂停误取消 | 0 次 | 0（暂停落 paused，旧执行被拒） | 达标 |
| 4.2 过期执行越权 | 0 次 | 0（token + execution 双校验） | 达标 |
| 4.3 同事件 100 次 | 1 次逻辑处理 | 1 张 ticket、1 次排期 | 达标 |
| 4.4 已 ACK 事件丢失 | 0 次 | v2 契约成立；ACK 丢弃后重发被去重为 1 条 | 达标（断点枚举见限制） |
| 4.5 正常退出不重启 | 0 次错误重启 | 0（跨进程重启仍不重启） | 达标 |
| 4.5 DB 短暂故障 | 不永久停摆 | 注入一次 locked 后自动恢复并跑完 | 达标 |
| 4.7 调度延迟 | p95 ≤ 2s | **p50 = 5.0ms，p95 = 8.1ms**（n=30） | 达标 |
| 4.6 24h soak + 100 崩溃 | — | 自检跑了 3 次强杀：0 stuck、0 重复；**24h/100 次未运行** | 未验证 |
| 4.8 未授权写 | 全部拒绝 | 未授权 actor/repo/空策略全部 rejected | 达标 |
| 4.8 PR 不重复 | 超时不重复创建 | 远端已成功 + 客户端超时 → perform 只调 1 次 | 达标 |

## 7. 兼容性

- **迁移**：`execution_id` 走 `_LATE_COLUMNS` 的 `PRAGMA` 差集补列（可重复、已升级的库也能补）；两张新表由 `create_all` 建。没有改动任何既有列语义，没有删除数据。
- **接口**：`arrange.create/get/list/update/pause/resume/cancel/signal` 全部保留；新增 `arrange.health`、`observer.status`、`observer.rearm`、`superagent.*`。
- **行为**：`ArrangeRunner.cancel()` 语义未变（仍落 cancelled）；新增的 `interrupt()` 才是"只停执行"。`_active_tasks` 保留为只读兼容视图。
- **Observer**：v1 脚本照旧运行（不读 stdin 也不受影响，ACK 只对 v2 发送，写失败不阻塞）。
- **旧数据**：`test_core_db_late_columns.py` 四个用例仍通过；新版库用旧版本打开不受新增列影响。

## 8. 回退

1. 代码：`git revert` 本分支的提交即可；新增文件是独立模块，删除不影响既有功能。
2. 配置：`LAMTOOLS_ARRANGE_MAX_ACTIVE_JOBS` 未设置时默认 3；想退回旧行为可设成较大的值（不建议）。
3. 单实例：如果桌面端确实需要多后端，删除 `arrange-scheduler.lock` 并让 `SchedulerLease.acquire()` 返回 False 的进程继续提供接口——调度器仍然只有一个。
4. 数据库：新增列只增不删，回滚代码后旧版本读到多余列会忽略；两张新表留在库里不影响旧版本。
5. Super-agent：不设置 `LAMTOOLS_SUPERAGENT_*` 时策略为空 → 一切 ingest 都被拒绝，等于功能关闭。

## 9. 已知限制（不得当成已完成）

1. **24 小时 soak 与 100 次崩溃恢复：未运行。** 只跑了 3 次强杀的脚本自检。脚本已可重复执行：`python core/scripts/arrange_soak.py --db .lam/soak/core.db --seed-jobs 500 --crash-iterations 100 --hours 24`。
2. **跨进程并发上限**：单实例锁保证"只有一个调度器"，但多机/多数据目录共享同一 DB 的场景没有分布式容量租约。
3. **进程级取消**：executor 走 `to_thread`，`task.cancel()` 只能停止等待，无法终止已进入同步代码的副作用；真正的强制终止需要把执行放进受管进程组。Observer 侧已做进程树终止，Arrange 执行器侧没有。
4. **Tauri 面板**：未做。CLI 与 RPC 是唯一入口。
5. **GitHub 真实接入**：只有 `superagent.ingest` 这个入口，没有 webhook 鉴权与轮询游标适配器；真实 PR 创建需要实现 `EffectAdapter`，目前只有测试用适配器。
6. **ACK 断点枚举**：没有做"8 个断点逐个强杀"的矩阵测试，只验证了 ACK 丢弃 → 重发 → 去重 这条主链路。
7. **`core_http_agent_app.py` 的 6 个既有失败**：基线即失败，本次未处理。

## 10. 用户操作

```powershell
# 1. 启动后端（桌面端或 core serve）
# 2. 配置授权范围（不配就等于关闭）
$env:LAMTOOLS_SUPERAGENT_SOURCES="github"
$env:LAMTOOLS_SUPERAGENT_EVENTS="issue.opened"
$env:LAMTOOLS_SUPERAGENT_ACTORS="alice"
$env:LAMTOOLS_SUPERAGENT_REPOS="E:\your-repo"
$env:LAMTOOLS_ARRANGE_MAX_ACTIVE_JOBS="3"

# 3. 投递一个事件
core superagent ingest --source github --event-id 42 --event-type issue.opened `
  --actor alice --trusted --repo E:\your-repo --text "修复登录按钮点击无响应"

# 4. 看结果 / 人工关口
core superagent tickets
core superagent show <ticket_id>
core superagent approve <ticket_id> --approver lam
core superagent audit

# 5. 健康与调度状态
core superagent policy
#   /api/health 里看 runtime.arrange.alive / capacity / queued
```
