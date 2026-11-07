# 执行隔离与强杀闭环：审计报告

> 分支 `sunday/reliable-base`，基线 39dd5c26。本轮不合并、不做界面、不加新功能。
> 配套：`agent_docs/superagent_reliability_audit.md`、`agent_docs/superagent_feature_matrix_and_plan.md`、`agent_docs/superagent_implementation_report.md`。

## 1. 这一轮解决什么

`asyncio.to_thread` 里的同步执行无法被 `task.cancel()` 终止，所以过去的“取消/超时”只是不再等结果，命令还在后台继续写工作区。本轮把“这次执行还作数吗”做成显式对象，并在**真正产生副作用的两处边界**强制它。

不改 Agent Loop：工具调用、会话、模型流程一行没动。

## 2. 变更

### 2.1 新增

| 文件 | 作用 |
|---|---|
| `core/src/lamtools_core/runtime/execution_guard.py` | 执行代际守卫：吊销开关 + 进程属主登记 + 上下文绑定 |
| `core/tests/test_execution_guard.py` | 7 例：吊销后禁止启动、取消真杀进程、超时真杀进程、租约失效吊销 |
| `core/tests/test_crash_residue.py` | 3 例：宿主 `/F` 强杀后子进程死亡、结果未落库可恢复、幂等副作用 |
| `core/scripts/reliability_soak.py` | 故障注入 + 随机崩溃 + 24h 长跑，直接产出量化指标 |

### 2.2 修改

| 文件 | 改动 |
|---|---|
| `runtime/arrange.py` | 每次执行建守卫；`interrupt()`/`stop()`/租约失效先吊销再杀进程树；新增 `job_timeout_seconds` 超时路径；`health()` 暴露 `live_processes`/`revoked_executions` |
| `tool/command.py` | 命令启动前查代际（已吊销连进程都不许起）；启动后把进程树登记到本次执行；新增 job object 公开包装、`_as_popen` 穿透 asyncio transport |
| `tool/command_runner.py` | 后台命令同样受代际约束与登记 |
| `tool/default_toolbox.py` | `prepare_call` 在已吊销时硬拒工具调用（返回 HARD_BLOCK） |
| `runtime/observer.py` | 观察器子进程登记进 kill-on-close job；停止时优先用 job 终止整棵树 |
| `app/http_agent_app.py` | `job_timeout_seconds` 接线，默认 3600 秒，`0` 关闭 |

## 3. 闭环核对

### 3.1 进程隔离

| 场景 | 机制 | 验证 |
|---|---|---|
| 取消 running 任务 | 吊销 → `terminate_all()` 杀进程树 → 取消协程 | `test_cancel_kills_the_running_command`：子进程 pid 真的消失 |
| 超时 | `wait_for` → 吊销 → 杀树 → `fail_run("timed out")` | `test_timeout_kills_the_running_command_and_fails_the_run` |
| 租约失效 | 续租失败 → 吊销 → 杀树 → 取消协程 | `test_lease_loss_revokes_the_execution` |
| 吊销后继续干活 | 命令启动前 `ensure_spawn_allowed()`；工具出口硬拒 | `test_revoked_execution_cannot_start_a_command` |
| 宿主被 `/F` 强杀 | 命令侧：kill-on-close job 句柄随宿主关闭 → 整棵树被回收 | `test_hard_killed_host_leaves_no_child_processes` |

### 3.2 执行代际 fencing

闭环成立：`execution_id`（随机）+ `fencing_token`（单调）+ `revision`（CAS）三层同时校验；`renew/checkpoint/complete/fail` 全部带 execution 校验；旧执行在任何一处写入都会失败，且失败被计为 `stale_execution_rejected` 而不是异常上抛。

新增强化：**吊销不等于等它自己停**。吊销后 `to_thread` 里的代码即便继续跑，它下一次想产生副作用（起命令、调工具）会被立即拒绝。

### 3.3 SQLite 任务状态

闭环成立：`running` 必须持有 `(worker_id, execution_id, fencing_token, 未过期租约)` 才能写；崩溃后由租约过期回收，`execution_id` 清空、代际递增，旧记录无法回写。

“执行成功但结果未落库”已验证：`complete_run` 失败一次后任务被重试并最终 `completed`（`test_result_not_persisted_is_retried_without_duplicate_side_effects`），第二次执行的副作用因 outbox 幂等键与“先查后建”而不重复（`test_effect_outbox_makes_retry_idempotent`）。

## 4. 强杀与残留：实测结果（含未达标部分）

| 尝试 | 做法 | 100 次强杀后的孤儿观察器 | 结论 |
|---|---|---|---|
| 1 | 观察器子进程不登记 | 每次崩溃留 1 个，累计 5+ | 缺陷 |
| 2 | 每个子进程 spawn 后 `AssignProcessToJobObject` | 4 / 117 次 spawn | 大幅改善，仍有窗口 |
| 3 | 把宿主自己也放进 kill-on-close job | 7~10 | **更差，已撤回** |
| 4 | `CREATE_SUSPENDED` → 登记 → 恢复 | 10 | **更差，已撤回** |

最终保留方案是第 2 种。为什么 3 和 4 反而更差，两条都写下来避免以后重复踩：

- 宿主进 job 之后，子进程**继承 job 句柄**；`KILL_ON_JOB_CLOSE` 只在最后一个句柄关闭时触发，幸存子进程自己握着句柄，于是永远不会被杀。
- `CREATE_SUSPENDED` 下 asyncio 的 Windows transport 在进程仍挂起时就开始等它，恢复与等待竞争，反而扩大了“未登记就跑”或“挂了没恢复”的窗口。

**未达标项（不得当作已完成）**：宿主在观察器 spawn 与登记之间的毫秒级窗口内被强杀时，会留下孤儿进程。100 次强杀实测 **4 个**（117 次 spawn）。命令侧（Arrange 执行器）通过同样的 job 机制验证为 0 残留，因为命令在启动后立刻登记且宿主不会在其间退出。

下一步要彻底消除，只有一条路：不用 `asyncio.create_subprocess_exec`，改成 `CreateProcess` + `PROC_THREAD_ATTRIBUTE_JOB_LIST`（创建时即带 job）或 `CREATE_SUSPENDED` + 同步 `ResumeThread` 自管句柄。这已经超出“只隔离执行环境”的范围，需要单独立项。

## 5. 100 次随机崩溃恢复

命令：`python core/scripts/reliability_soak.py --root .lam/crash100d --crashes 100 --seed-jobs 80 --observer-events 20`
脚本每轮 `taskkill /T /F` 宿主，然后重启，最后核对数据库与磁盘。

| 指标 | 值 |
|---|---|
| 崩溃次数 | 100 |
| 任务总数 | 81（80 个一次性 + 1 个事件订阅） |
| 最终状态 | completed 80，waiting 1（观察器在等事件，正常） |
| 卡在 running | **0** |
| 并发峰值（按进程分别统计） | **3**（上限 3） |
| 实际执行次数 | 117（崩溃导致至少一次重跑，符合语义） |
| 重复 occurrence | **0** |
| 事件信号数 | 100（50 个跨轮重放 + 订阅作业），无丢失重复 |
| 重复副作用尝试 | **0** |
| 重复副作用记录 | **0** |
| 残留受管子进程 | **0** |
| 恢复时间中位数（强杀→重新领取） | **1.27 秒** |
| 内存（RSS）首/末 | 104.2 MB → 101.6 MB，无增长趋势 |

初次统计时把“进程被杀导致 `job_end` 缺失”算成了并发堆积，得出 19 的假峰值；已改成按进程分别统计并写进脚本注释。

## 6. 基线失败复核与回归

原始 HEAD（`E:/LamTools/.lam/tmp/wt-superagent`）与分支跑同一批 11 个测试文件：

| 树 | 结果 |
|---|---|
| 原始 HEAD | 7 failed, 202 passed, 1 skipped |
| 本分支 | 7 failed, 202 passed, 1 skipped |

失败项名称完全一致：

1. `test_durable_tools.py::TestGoalTool::test_unknown_action_fails_without_calling_operation`（产品提示词多了 `complete`，测试断言旧文案）
2. `test_core_http_agent_app.py::test_core_agent_http_app_owns_attachment_storage`（附件落盘路径假设）
3. `test_core_http_agent_app.py::test_core_http_sessions_survive_app_restart`
4. `test_core_http_agent_app.py::test_core_http_session_delete_removes_persisted_thread`
5. `test_core_http_agent_app.py::test_project_http_round_trip_survives_restart_and_uses_agents_md`
6. `test_core_http_agent_app.py::test_core_http_websocket_active_turn_steer_and_second_start_matrix`
7. `test_core_http_agent_app.py::test_core_http_websocket_rejects_steer_after_kernel_seal_before_task_done`

**注意**：先前报告写的“6 项基线失败”不准确，真实是 **7 项**，第 1 项是这轮复核时新发现并已在原始 HEAD 上复现。**本分支没有引入新失败。**

新增用例：`test_execution_guard.py` 7 例、`test_crash_residue.py` 3 例，全部通过。加上上一轮的 26 例，本分支新增 36 例。

## 7. 24 小时 Soak

已启动：`--hours 24 --crashes 20 --seed-jobs 200 --observer-events 50 --feed-interval 10`。

指标口径：每 60 秒一条 `heartbeat`（RSS、在跑数、受管子进程数），结束后一次性输出并发峰值、事件丢失、重复副作用、残留进程、恢复时间、最终状态。

**当前状态：进行中，尚未得出 24 小时结论。** 需要说明的是，24 小时是一个时间门槛，不是可以加速的指标；本轮已经拿到的是 100 次崩溃的完整数据，两者不能互相替代。查看方式：

```powershell
# 实时
Get-Content .lam/soak24.log -Tail 5
# 心跳与内存趋势
Select-String -Path .lam/soak24/metrics.jsonl -Pattern heartbeat | Select-Object -Last 5
# 结束后看结论
Select-String -Path .lam/soak24.log -Pattern "verify|result" -Context 0,25
```

## 8. 合并建议

不建议现在合并，理由按优先级：

1. 观察器孤儿进程的毫秒级窗口未闭合（实测 4/117），要么接受为已知限制并写进文档，要么先做 `CreateProcess` + job list 的单独立项。
2. 24 小时 soak 还没跑完，长跑结论缺失。
3. 7 项基线失败与本轮无关，但会掩盖将来真正的回归，建议单独安排一次清理。

可以合并的前提：接受第 1 条作为已知限制并记录，且 24 小时 soak 通过。

## 9. 已知限制

1. 观察器 spawn→登记的竞态窗口（见第 4 节），未闭合。
2. 执行器内部若用纯 Python 直接写文件（不经命令、不经工具出口），吊销只能阻止后续动作，不能打断正在写的那一次系统调用。
3. 超时默认 3600 秒；长任务需要显式调大，否则会被判超时并重试。
4. 24 小时 soak 结论待补。
5. 僵尸进程未单独统计：Windows 无僵尸语义；POSIX 侧靠 `wait()` 回收，未在本机验证。
