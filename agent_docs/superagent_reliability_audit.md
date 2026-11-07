# Sunday 可靠底座审查与复现报告

> 对照附件《Sunday SuperAgent 可靠底座设计包》在当前 HEAD 上逐项复核。
> **本文件只报告事实与证据；未修改任何正式源代码。**
> 复现测试位于隔离工作树，未写入主工作区。

## 1. 环境与基线

| 项目 | 值 |
|---|---|
| 仓库 | E:\LamTools |
| 当前分支 | codex/plugin-market-0.3.23 |
| HEAD | 39dd5c26 `release: Sunday 0.3.37 with Ping capture window and pet settings fixes` |
| 设计包参考提交 | 7627083244655b6c0c3e13f0188b4480f383c6fd（本地不存在，无法逐行比对，改为按函数复核） |
| Python / pytest | 3.14.4 / 9.0.3（pytest-asyncio 1.3.0，asyncio_mode=auto） |
| 平台 | Windows 11，SQLite（aiosqlite + SQLAlchemy 2.x） |
| 工作树状态 | 存在大量未提交的桌宠相关改动；本次审计与之无交集 |
| 隔离工作树 | `E:\LamTools\.lam\tmp\wt-superagent`（`git worktree --detach HEAD`，位于 .lam 忽略区） |
| 测试数据库 | 全部使用 `InMemoryArrangeStore` 与 pytest `tmp_path` 下的独立 SQLite；未触碰 `data/core.db` |

基线回归：现有相关测试 **35 passed**（`test_arrange_runtime.py`、`test_arrange_fencing.py`、`test_observer_runtime.py`、`test_durable_operations.py`、`test_core_db_late_columns.py`）。

## 2. Skill 使用说明

附件要求“优先查找并按项目规范调用现成许愿 Skill”。实测结果：

- `MyProject/plugins/wishwright-skills/plugin.json` 声明的插件名为 **wishwright-skills**，含 13 个 skill 目录。
- 其中的“许愿”Skill 为 **`skills/wish-understanding/SKILL.md`**，已通过 `load_skill` 正式加载并按其方法论执行（区分请求结果 / 硬约束 / 主观偏好 / 未知项；不把设计包结论当既成事实）。
- 用户在本轮确认“那个 skill 叫做 wishwright，是一套 skill”，与上述一致。

## 2.1 与设计包基线的差异（决定哪些结论已过期）

设计包基于提交 `7627083244655b6c0c3e13f0188b4480f383c6fd`，该提交的本地工作树仍在
`C:/Users/Administrator/.codex/worktrees/aa8c/LamTools`，可以直接对比。两者之间相隔 **723 个提交**：

| 文件 | 76270832 → 39dd5c26 变化 |
|---|---|
| `app/core_db.py` | +1839 / −…（fencing 字段、迁移、大量 store 扩展） |
| `app/http_agent_app.py` | +1352 / −…（启动恢复、活连接、子 agent 回收） |
| `runtime/arrange.py` | +207 / −…（fencing_token、租约回收、取消落库） |
| `app/sqlite_write.py` | +166 / −…（写协调器、PRAGMA、退避） |
| `app/durable_operations.py` | 6 行 |
| `runtime/observer.py` | **11 行** |

由此可以确定三件事：

1. **fencing 是基线之后补上的**：`git log -S fencing_token` 命中 `90f284ae chore: checkpoint current core development`。设计包“只认 worker_id”的结论对 `76270832` 成立，对当前 HEAD 已过期。
2. **`max_active_jobs` 在任何分支都从未出现**：`git log -S max_active_jobs --all` 无命中。并发上限是真空白，不是回归。
3. **Observer 几乎没被碰过**：11 行改动只有两项，把 `os.environ.copy()` 换成 `subprocess_env()`，以及把单行解析的 `except` 放宽为 `except Exception`。`on-failure` 重启判定（`:209`）、`readline` 的 `limit` 与死分支（`:196`、`:232`）、无 ACK 的协议（`:22`）全部原样保留，所以第 4.4、4.5、5.1 节的问题与基线完全一致。

这三条说明：不能机械套用设计包的行号与结论，必须按当前函数逐个复核（本报告即按此完成）。

## 3. 六项复核结论总表

| # | 设计包结论 | 当前 HEAD 实际 | 判定 |
|---|---|---|---|
| 1 | 并发限额被绕过（`claim_limit` 是每轮上限） | 完全成立，且无任何并发配置项 | **真实缺陷** |
| 2 | 运行中暂停被落成取消 | 完全成立，暂停请求直接报错，任务已被取消 | **真实缺陷**（最严重） |
| 3 | 执行权只认 `worker_id` | 设计包结论已过时：`fencing_token` 已存在并全程 CAS | **已修复**，但残留 1 个真实缺口 |
| 4 | Observer 事件游标与 ACK 脱节 | 成立：仅 v1 无 ACK、无 spool、无重放 | **真实缺陷** |
| 5 | `on-failure` 正常退出仍重启 | 成立，且比设计包描述更严重：是持续热循环 | **真实缺陷** |
| 6 | 后台循环会静默退出 | 成立：循环无异常边界，`/api/health` 与实际状态脱钩 | **真实缺陷** |

结论：6 项中 **5 项成立、1 项已大部分修复但有残留缺口**，0 项误报。另有 **2 项设计包未列出的阻断性缺陷**（第 8 节）。

## 4. 逐项证据

### 4.1 总并发上限不存在

**代码事实**

- `core/src/lamtools_core/runtime/arrange.py:1038` `ArrangeRunner.__init__` 只有 `claim_limit`，没有 `max_active_jobs`。
- `core/src/lamtools_core/runtime/arrange.py:1120` `run_due_once` 以 `limit=self.claim_limit` 领取，`_active_tasks` 只在 `:1141` 记账，从不参与容量核算。
- `core/src/lamtools_core/app/http_agent_app.py:617` 构造 Runner 时未传任何并发参数，即 `claim_limit=4`、`poll_interval=1.0`。

**复现**：`test_peak_concurrency_never_exceeds_configured_limit`

```
AssertionError: 峰值并发 16 超过配置上限 3（领取数与活跃数没有互相扣减）
```

5 轮领取、每轮 10 个即达 16 个线程同时在跑。轮询越快、排队越多，峰值越高，没有上界。

**附带缺口**：仓库没有进程级单实例互斥。`core/src/lamtools_core/plugin_system/file_lock.py:16` 的 `locked_file` 是写入期上下文锁，不是常驻锁。两个宿主进程各自开一个 Runner 时，并发上限叠加且互不知情。

### 4.2 运行中暂停被落成取消

**代码事实**（调用链）

1. `core/src/lamtools_core/app/durable_operations.py:181`：`current.status == "running"` 且目标为 `paused` → 调用 `cancel_running(job_id)`。
2. 绑定实参 `core/src/lamtools_core/app/http_agent_app.py:632`：`cancel_running=arrange_runner.cancel`。
3. `core/src/lamtools_core/runtime/arrange.py:1086` `cancel()`：先 `task.cancel()`，再把任务**持久化为 `cancelled`**（`:1100-1108`，`fencing_token + 1`）。
4. 回到 `durable_operations.py:188` 调用 `update_status(job_id, "paused")`。
5. `core/src/lamtools_core/runtime/arrange.py:812` `update_status` 读到终态 `cancelled`，抛 `ValueError("Arrange job is terminal")`。

**复现**：`test_pausing_a_running_job_keeps_it_paused`

```
AssertionError: 暂停请求被拒绝: {'error': 'Arrange job is terminal: arrange_f1beeb23c4c049a4abbb2a899dfa01a9'}
```

用户视角：点了“暂停”，得到一条报错，任务实际已被取消、不可恢复。**误取消率 100%**，4.2 的“0 次暂停误取消”当前不可能达标。

**附带缺口**：executor 经 `asyncio.to_thread` 执行（`arrange.py:1207`），`task.cancel()` 只能停止等待，无法终止线程里已开始的同步副作用；`termination_pending` 概念未落地。

### 4.3 租约 fencing：主体已修复，残留一处真实越权

**已具备**（设计包结论过时，不要重复实现）

| 能力 | 位置 |
|---|---|
| `fencing_token` 字段（单调递增领取代际） | `runtime/arrange.py:143`、`app/core_db.py:536` |
| 每次 claim 递增 | `runtime/arrange.py:406`、`app/core_db.py:1718` |
| `renew/checkpoint/complete/fail` 全部带 token CAS | `app/core_db.py:1754/1795/1834/1910` |
| `_owned_running` 校验 token | `runtime/arrange.py:684`、`app/core_db.py:2109` |
| 幂等补列迁移 | `app/core_db.py:2768`（`ADD COLUMN fencing_token`） |
| 回归用例 | `core/tests/test_arrange_fencing.py`（3 个，全部通过） |

**残留真实缺口**：`ArrangeRunner._active_fences` 以 `job_id` 为键（`arrange.py:1139`）。同一 Runner 内租约过期被重新领取时，该字典被覆盖为新 token；旧执行调用公开的 `runner.checkpoint(job_id, ...)`（`:1149`）读到的就是**新 token**，从而通过 fence 校验，把过期执行的进度写进新执行的检查点。

**复现**：`test_stale_execution_cannot_write_checkpoint_of_new_execution`

```
AssertionError: 过期执行通过了 fence 校验并写入了检查点
```

同一处 `_active_tasks[job_id]`（`:1141`）同样被覆盖，导致 `stop()`/`cancel()` 只能看到最新一个执行，旧执行变成无人管理的孤儿任务。

**与设计包的差异**：设计包要求 `execution_id`（每次领取随机 UUID）+ `lease_epoch`。当前只有单调整数 `fencing_token`，功能上等价于 `lease_epoch`，能满足越权拒绝；但没有随机 `execution_id`，审计串联（Signal → Occurrence → Attempt → Effect）缺少稳定标识。属增强项，不是缺陷。

### 4.4 Observer 事件投递不可靠

**代码事实**

- 协议只有 `lamtools.signal.v1`（`runtime/observer.py:22`），无 v2。
- 子进程 `stdin=asyncio.subprocess.DEVNULL`（`:196`），宿主无法回 ACK。
- `_read_stdout`（`:221`）在 `manager.emit_signal` 失败时只写 `last_error`（`:267-274`），没有 spool、没有重放。
- 观察器脚本一旦打印完就自己推进游标（现有用例 `test_observer_catches_up_events_created_while_core_was_off` 即此模型），宿主侧失败后没有任何补偿路径。

**已被正确实现、应复用的部分**（避免重复造）

- 事件去重按主键：`app/core_db.py:2023` `db.get(CoreArrangeSignal, event_id)`，同事务内 `BEGIN IMMEDIATE`，重复投递返回 `created=False`，不产生第二条 occurrence。
- Observer 事件 ID 被稳定化：`runtime/observer.py:342` `_bound_event_id(job_id, event_id)`，所以重放天然去重。

也就是说：**去重已经好了，缺的是“投递后确认”这一环**。

**复现**：`test_observer_event_survives_transient_host_write_failure`

```
AssertionError: 事件最终入库 was not met before timeout
```

宿主写库瞬时失败一次（`database is locked`），该事件永久消失。4.4 的“0 次已确认事件丢失”当前无适用前提（没有 ACK 机制），4.3 的“100 次重复只处理一次”在直接 `arrange.signal` 路径上已可达。

### 4.5 `on-failure` 正常退出被反复重启

**代码事实**

- `runtime/observer.py:209`：`restart_policy == "on-failure" and return_code == 0` → 只 `_set_state(status="stopped")` 就 `return`。
- 没有记录持久终态，也没有设置 `self._next_start`。
- `reconcile_once`（`:123`）的 `desired` 取自 `store.list()` 里 `observer 非空且状态属于 scheduled/waiting/running` 的任务。观察器任务本身仍是 `scheduled`/`waiting`，因此**下一轮轮询立即重启**（默认 `poll_interval=2.0`）。

**复现**：`test_on_failure_observer_exiting_cleanly_is_not_restarted`

```
AssertionError: 正常退出的观察器被重启了 24 次
```

1.5 秒内 24 次。真实默认轮询 2 秒时是每 2 秒一次的**无限热循环**，比设计包描述的“重启 Sunday 后才重启”严重得多。

### 4.6 后台循环静默死亡 + 健康检查失真

**代码事实**

- `runtime/arrange.py:1174` `_run`：`await self.run_due_once()` 没有异常边界；`claim_due` 抛任何异常，`asyncio` 任务即结束。
- `runtime/arrange.py:1069` `create_task(self._run())` 没有 done 回调，结束时不写日志、不告警。
- `runtime/observer.py:143` `_run`：`reconcile_once()` 里 `store.list()` 失败同样直接结束。
- `app/http_agent_app.py:784` `health_payload` 是静态 dict，`status` 恒为 `"ok"`，不读任何后台状态。
- 无统一后台任务台账：子代理确认 `RuntimeTaskRegistry`（`runtime/__init__.py:436`）只登记会话级 agent 运行，不覆盖 arrange/observer/memory-resume 循环。

**复现**

```
test_arrange_loop_survives_transient_database_failure
  AssertionError: 任务在数据库恢复后被执行 was not met before timeout

test_arrange_and_observer_expose_live_health_snapshot
  AssertionError: ArrangeRunner 没有健康快照，无法判断调度是否还活着
```

一次 `database is locked` 就让调度器永久停摆，而 HTTP 仍返回 `status: ok`。4.5 的“数据库短暂故障不造成永久停摆”当前不成立。

## 5. 设计包未列出、但阻断验收的两项缺陷

### 5.1 超长 JSONL 行使信号读取永久失效

`runtime/observer.py:196` 给子进程设置了 `limit=self.max_line_bytes + 1`，`:226` 的 `readline()` 遇到超限行会抛 `ValueError`，而该调用在 `try` 之外（`:225-230`）。异常使 `_read_stdout` 任务结束，`_monitor` 的 `gather(..., return_exceptions=True)`（`:208`）把它吞掉，进程继续运行但**此后再也不读任何事件**。`:232` 的 `len(line) > self.max_line_bytes` 分支是死代码，永远不会执行。

**复现**：`test_oversized_observer_line_does_not_kill_signal_reader` → `AssertionError: 超长行之后的合法事件 was not met before timeout`

### 5.2 Observer 无进程组管理

`runtime/observer.py:196` 以 `CREATE_NO_WINDOW` 启动，`_stop_process`（`:287`）只 `terminate()` 直接子进程。观察器脚本自己起的孙进程不会被回收，A4 的“关闭后不残留子进程”无保证。

## 6. 复现测试清单

文件：`core/tests/test_arrange_reliability_gate.py`（隔离工作树内，477 行，8 个用例）

| 用例 | 对应验收 | 修复前 |
|---|---|---|
| `test_peak_concurrency_never_exceeds_configured_limit` | 4.1 | **FAIL**（峰值 16） |
| `test_pausing_a_running_job_keeps_it_paused` | 4.2 | **FAIL**（被取消） |
| `test_stale_execution_cannot_write_checkpoint_of_new_execution` | 4.2 | **FAIL**（越权写检查点） |
| `test_on_failure_observer_exiting_cleanly_is_not_restarted` | 4.5 | **FAIL**（重启 24 次） |
| `test_observer_event_survives_transient_host_write_failure` | 4.3/4.4 | **FAIL**（事件丢失） |
| `test_arrange_loop_survives_transient_database_failure` | 4.5 | **FAIL**（循环死亡） |
| `test_arrange_and_observer_expose_live_health_snapshot` | 4.5 | **FAIL**（无健康面） |
| `test_oversized_observer_line_does_not_kill_signal_reader` | 5.1 | **FAIL**（读取失效） |

结果：`8 failed in 24.42s`，完整日志 `.lam/tmp/superagent/repro-before.log`。

### 6.1 一次自我纠错记录（重要）

首版用例中有两个“通过”是假通过，已修正，记录在此以免后续再犯：

1. 并发用例最初在两次 `run_due_once()` 之间不 `await`，事件循环不让出，`create_task` 排队的任务根本没启动，`peak` 恒为 0。修正为每轮 `await asyncio.sleep(0.1)`，并新增“必须真的制造出 ≥3 个并发，否则断言无效”的前置断言。
2. fence 用例最初让第二次执行立刻完成，过期执行被“任务已完成”挡住，测出的不是 fence 本身。修正为第二次执行持续持有租约，并断言 `saved.status == "running"` 作为前提。

这两条已写进用例注释，属于“不得用弱断言伪装可靠性”的落地约束。

## 7. 兼容性与迁移现状（决定后续实现方式）

| 事项 | 现状 | 位置 |
|---|---|---|
| 建表 | `CoreDbBase.metadata.create_all`，新表写 ORM 模型即自动建 | `app/core_db.py:2180` |
| 加列主通道 | `_LATE_COLUMNS` 映射 + `_ensure_late_columns`，每轮启动按 `PRAGMA table_info` 差集补列，天然幂等 | `app/core_db.py:2374`、`:2406`、`:2412`、`:2420` |
| 版本号 | `core_db_metadata` 表 + `CORE_SCHEMA_VERSION = 3`，`schema_version < 3` 才跑 `_migrate_core_app_schema` | `app/core_db.py:83`、`:2188`、`:2524` |
| 一次性数据修复 | 用 metadata marker 标记，参考 `THREAD_REVISION_REPAIR_MARKER` | `app/core_db.py:2481` |
| 写路径 | 全部走 `SQLiteWriteCoordinator.run`：`BEGIN IMMEDIATE` + 3 次退避重试（0.05/0.15/0.35s）+ 5s `busy_timeout` | `app/sqlite_write.py:145`、`:147`、`:183`、`:196` |
| 迁移测试 | `test_core_db_late_columns.py` 4 个用例覆盖幂等与旧库补列；**版本门控迁移无回归用例** | `core/tests/test_core_db_late_columns.py:72/87/117/154` |

**实施口径**：新增字段一律“ORM 模型 + `_LATE_COLUMNS` 登记”，不往 `_migrate_core_app_schema` 里塞非幂等语句；新增表写 ORM 模型即可，但给旧表补索引要单独 DDL。

## 8. 已确认可复用的既有能力（禁止重造）

| 能力 | 位置 | 说明 |
|---|---|---|
| 工具白名单 + 权限等级上限 | `tool/default_toolbox.py:1585/1883`、`tool/approval.py:248/258`、`app/runtime_permissions.py:300` | 列出与执行双点强制，模型无法自我扩权 |
| 子 Agent 独立 work_root | `tool/sub_agent_runner.py:232/285/469` | 可作为 Ticket 的隔离执行入口 |
| OperationCatalog 注册 | `app/operation_catalog.py:52/100`、`app/operation_groups.py:116/137` | 新能力照 `durable_operations.py:293-302` 写法加命名空间 |
| CLI 暴露 | `cli_commands/parser.py:52`、`cli_commands/parse_workspace.py:218-248` | `core arrange new / ls / describe / set` 已可用 |
| 事件幂等 | `app/event_store.py:105/110/245` | event_id 与 client_message_id 双去重 |
| 写入期文件锁 | `plugin_system/file_lock.py:16` | 可改造为进程生命周期单实例锁 |
| arrange 信号去重 | `app/core_db.py:2023`、`runtime/observer.py:342` | 去重已成立，只缺 ACK |

## 9. 未验证项（不得当作已达标）

- **24 小时 soak 与 100 次随机崩溃恢复：Not run。**
- **调度延迟 p95 ≤ 2 秒：Not measured。** 当前默认 `poll_interval = 1.0`，理论量级可用，但未实测。
- **跨进程并发上限：未设计。** 当前只有单进程语义。
- **Windows 强杀后的子进程回收：Not run。** 现有代码无进程组管理，预期不合格。
- **真实 GitHub 权限与 PR 幂等：当前代码库无 PR 能力**，属待新建。

## 10. 需要用户确认的决策

见配套文档 `agent_docs/superagent_feature_matrix_and_plan.md` 第 6 节。
