# 孤儿进程修复：范围、根因与证据

> 分支 `sunday/reliable-base`。未 push、未 merge、未做 UI。

## 1. 真正的根因（两处，都在 job 限制上）

`KILL_ON_JOB_CLOSE` 从来没有生效过，不是一个地方错，是两个常量/偏移叠加：

| 位置 | 错误 | 正确 |
|---|---|---|
| 常量值 | `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00000200` | `0x00002000`（0x200 是 `JOB_MEMORY`） |
| 结构体偏移 | `LimitFlags` 写在偏移 40 | 偏移 16（偏移 40 是 `ActiveProcessLimit`） |

影响面：`tool/command.py` 里原有的 Windows Job 代码也是这两个错，所以**产品里所有
“句柄关闭即杀进程树”的语义此前都不成立**——命令执行器之所以看起来正常，是因为它
走的是 `TerminateJobObject`（显式终止），而不是 kill-on-close。

定位过程（都是实测，不是推演）：

1. 注入器 10 轮 × 2 个孤儿 → 说明“宿主死了，子进程没死”。
2. `IsProcessInJob(child, job)` 返回 True → 成员身份是好的，问题在“关闭即杀”没设上。
3. `SetInformationJobObject` 用真实结构体 + 偏移 16 仍返回 87（`ERROR_INVALID_PARAMETER`）
   → 说明 `LimitFlags` 的值本身非法，才追到常量写成 0x200。
4. 常量改成 0x2000 后，最小实验从 `child alive after host kill: True` 变成 `False`。

顺带修掉一个 ctypes 陷阱：`ctypes.byref()` 不能当 `memmove` 的源、也不能直接喂给
声明为 `LPVOID` 的形参，传进去的是 `CArgObject` 而不是地址，结果写进结构体的是垃圾。
现在统一用 `bytes(struct)` + `from_buffer_copy`，或 `c_void_p(addressof(...))`。

## 2. 注入器改造（防卡死 + 防假通过）

- 每个阶段独立超时：启动 / 等树就绪 / 强杀 / 回收 / 稳定期 / 检查，任一步超时只算该轮失败。
- 强杀只用 `taskkill /F`，**不带 `/T`**：`/T` 会连带杀树，等于替被测代码兜底。
- `taskkill` 超时或异常时退回 `Popen.kill()`，批次永不阻塞。
- 每轮写 JSONL：宿主 pid、阶段耗时、退出码、kill 方式、标记数、孤儿明细。
- **防假通过**：必须同时观测到 `child-<pid>` 和 `grand-<pid>` 两个标记，这一轮才算有效；
  无效轮次单独计数，不进入验收；报告里同时给 `child_processes_observed`。

这一步抓到两次真实空转：第一版观察器脚本拿不到标记目录、启动即退；第二版宿主还没起完
就被杀。两次都报“0 孤儿”，两次都没有意义。

## 3. 实测结果

| 批次数 | 有效轮次 | 无效 | 超时 | 孤儿 | 耗时 |
|---|---|---|---|---|---|
| 10 | 10 | 0 | 0 | **0** | 20s |
| 100 | 100 | 0 | 0 | **0** | 193s |
| 1000 | 1000 | 0 | 0 | **0** | 1851s（1.85s/轮，最慢 4.76s） |

100 轮原始数据：`.lam/ki100/kill_injection_report.json` 与 `.lam/ki100/iterations.jsonl`
（逐轮阶段耗时与 pid）。

覆盖到的时机：树就绪后 0ms 强杀、以及按偏移扫描到 300ms 的不同阶段；观察器子进程和它
自己起的孙进程同时被检查。

## 4. 与上一版报告的差异

上一版写“宿主强杀后子进程与孙进程死亡 = PASS”是**错的**：那次用的 `taskkill /T`，
树是被 taskkill 杀的，不是 job 杀的。这次只用 `/F`，才暴露真相。

## 4.1 基线失败清理进度（7 项）

| # | 用例 | 归类 | 状态 |
|---|---|---|---|
| 1 | `test_durable_tools::test_unknown_action_fails_without_calling_operation` | 测试契约过期（产品已支持 `complete`） | **已修**（`6aa20f61`，断言强度不变，14 passed） |
| 2 | `test_core_http_agent_app::test_core_agent_http_app_owns_attachment_storage` | 落盘布局与断言不符（目录名仍是 `session-{digest}`，待查文件名/时机） | 未修 |
| 3-5 | `...sessions_survive_app_restart` / `...session_delete_removes_persisted_thread` / `...project_http_round_trip...` | 产品缺陷：`ValueError: future belongs to a different loop`，同一进程内重建 TestClient（新事件循环）时复用了绑定旧循环的对象；`core_db.py` 与 `sqlite_write.py` 里没有全局 engine 缓存，源头未定位 | 未修 |
| 6-7 | `...websocket_active_turn_steer_and_second_start_matrix` / `...rejects_steer_after_kernel_seal...` | 一个是 `model_started.wait(timeout=2)` 未触发（模型/环境依赖），一个同属循环归属问题 | 未修 |

## 5. 仍然没做

1. ~~1000 轮尚未完成~~ → 已完成：1000/1000 有效、0 孤儿、0 超时。
2. **7 项历史基线失败没修**，仍在原始 HEAD 上复现。
3. **取消后副作用专项测试没做**：纯 Python 文件写入、网络请求在取消后的表现，
   以及“哪些能强制终止、哪些只能靠幂等/原子写/补偿”还没有专门用例。
4. **24 小时 soak 覆盖的是更早的提交**，不含本轮改动，不能作为本轮验收依据。
5. 无人值守模式下“原子 job 创建失败必须阻止任务启动”还没落地：目前
   `_spawn_observer_child` 在原生路径失败时会降级到 asyncio 并写警告（对观察器是可用性
   优先的正确取舍），但按你的要求，任务执行路径应该 fail-closed，这条还没改。

## 6. 结论

机制现在是真的，小批量数据干净。但你给的门槛是 1000 轮有效强杀 + 基线修复 + 新提交长跑，
三条都还没齐，**不合并、不 push**。

## 7. 全量基线审计（进行中）

**全量套件的正确跑法**：必须从仓库根执行 `python -m pytest core/tests`。
从 `core/` 目录跑会在收集阶段就报 4 个 error（`ModuleNotFoundError: No module named 'core'`、
`test_plugin_packaging_boundary.py` 的 FileNotFoundError），这是导入路径问题，不是产品缺陷。

**第 8 项 `test_toolbox_missing_dependency_placeholder`（未修复）**

- 事实一：产品把"依赖缺失"归为 `blocked`（前置条件不满足、没有执行），断言已按此同步。
- 事实二：同步后仍失败，`result.error` 是 `Tool requires approval and was not routed
  through a waiting request.`，metadata 里 `requires_approval: True`。
- 说明**审批闸门先于依赖占位检查**执行，测试想验证的 "missing dependencies + pip install"
  在这个测试上下文里根本走不到。
- 待定：这是产品顺序问题（依赖检查应早于审批），还是测试缺少审批上下文，需要单独判断，
  不能用改断言掩盖。


## 8. 全量基线对照（首次完整跑）

命令（两棵树相同，均从仓库根执行）：

```powershell
python -m pytest core/tests -p no:cacheprovider -q
```

前置夹具：`.agents/` 被 gitignore，工作树里没有，需从主工作区复制一次；
否则 `test_plugin_packaging_boundary.py` 在收集阶段就 FileNotFoundError。

| 树 | passed | failed | skipped | 耗时 |
|---|---|---|---|---|
| 原始 HEAD（39dd5c26 工作树） | 4043 | 222 | 9 | 709s |
| 分支 `sunday/reliable-base` | 4089 | 205 | 9 | 696s |

集合对照：

- **分支修好 19 项**，含本次清理的 8 项基线，以及 `test_core_live_approval_switch_ws`
  两项、`test_core_live_client_e2e` 一项（都是跨循环问题，被插件 Task 修复带出来的）。
- **分支新增 2 项失败**，隔离运行均通过，判定为全量负载下的时序抖动，需在冻结提交上复测：
  - `test_v2_observer_advances_cursor_only_after_host_ack`：全量下 2 秒内只 ACK 了 1 个事件。
  - `test_search_network_limits.py::test_http_total_deadline_expires_despite_continuous_data`：
    全量下截止时间先到，第二次读取没发生。
- 其余 203 项为两棵树共有的既有失败（网络、模型、WSL、打包边界等环境依赖），本轮未动。

**注意**：全量 222 个既有失败说明这个仓库在本地环境的绿灯基线本来就很差，不能把
"分支 205 failed" 当成可接受状态；它只说明"没有比原始 HEAD 更差"。

## 9. 夹具修复与由此暴露的隐藏失败

`.agents/` 是 gitignore 的本地目录，独立工作树里没有，`test_plugin_packaging_boundary.py`
在模块顶层直接读它 → 收集阶段就崩，整个套件根本跑不起来。

修法：
1. 该文件的读取改成惰性（收集阶段不再碰文件系统）。
2. `core/tests/conftest.py` 增加会话级自动夹具：从 `git worktree list` 列出的任意检出里
   把 `.agents/skills` 复制过来；都找不到时给一条可操作的报错，而不是一个看不懂的
   FileNotFoundError。

实测：删掉 `.agents` 后直接跑该文件，夹具自动补回，3 passed。

**由此暴露两条此前被收集错误掩盖的既有失败（不是本轮引入）**：

- `test_local_packaging_boundary_checks_excluded_and_required_plugins`
- `test_release_workflow_boundary_checks_excluded_and_required_plugins`

两者都是把 `scripts/package.ps1` / `.github/workflows/release.yml` 的字面量写法
（`foreach ($ExcludedPlugin in @("workflow"))` 等）当契约，脚本重构后断言就失效。
分类：**测试契约过期（静态字符串断言绑定实现写法）**。要修得改成校验行为而不是字符串，
本轮未做。

## 10. 全量测试审计（第 1 项）

### 10.1 基线差异

| | pristine | branch |
|---|---|---|
| failed | 222 | 205 |
| passed | 4043 | 4089 |
| shared failures | — | **203** |
| 分支新增失败 | — | **2** |
| 分支修好 | — | **19** |

### 10.2 两项新增失败的复现结论

| 场景 | 结果 |
|---|---|
| 独立运行 ×5 | 5/5 通过 |
| 8 个 CPU 忙进程负载下 ×4 | 4/4 通过 |
| 全量套件（700 秒、4000+ 用例同一进程） | 失败 |

- `test_v2_observer_advances_cursor_only_after_host_ack`：全量下 `acked` 只到 1 个事件，
  即等待游标的 10 秒窗口内第二个事件没落库。
- `test_http_total_deadline_expires_despite_continuous_data`：截止时间先到，第二次读取没发生。

**结论：不是确定性回归，但也没能定性为纯环境问题。**只在"同一进程跑完 4000+ 用例"的
状态下复现，说明与进程内累积状态或系统长时间高负载有关，而不是我改动的那两个模块本身
（两者都不在改动范围内）。分类暂记 **偶发/环境时序（待冻结提交复测）**。
按你的要求没有靠加超时掩盖。

### 10.3 203 项共有失败的粗分类

按错误签名（不是逐个用例判定）：

| 类别 | 数量 | 说明 |
|---|---|---|
| `AssertionError` / `assert` | 175 | 断言不符，可能混合"测试契约过期"与"产品行为差异"，需逐个看 |
| `AttributeError` | 10 | 接口形状变化 |
| 环境类（Rust 控制器缺失、连接被拒、DNS） | ≈22 | 缺 `build-network-controller.ps1`、外网不可达 |
| `IndexError/TypeError/ValueError/KeyError` | 9 | 逻辑或契约 |
| `FileNotFoundError/ModuleNotFoundError` | 3 | 夹具/路径 |

失败最集中的文件：`test_default_toolbox.py`(27)、`test_context_compaction.py`(16)、
`test_kernel.py`(12)、`test_core_cli.py`(10)、`test_core_sub_agent_runner.py`(10)。

**这是粗分类，不是逐项定性。**要给出"每项属于产品缺陷/契约过期/环境缺失"的确定结论，
需要逐文件过一遍，本轮未做。

