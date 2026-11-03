# 孤儿进程修复：当前状态（未完成验收）

> 分支 `sunday/reliable-base`。**这一轮没有通过验收，不要合并。**
> 上一轮报告：`agent_docs/superagent_execution_isolation_report.md`。

## 1. 已完成：创建期原子入 Job

新增 `core/src/lamtools_core/runtime/win_job_spawn.py`，用 ctypes 直接调用：

```
CreateJobObjectW（KILL_ON_JOB_CLOSE）
CreatePipe ×3（父端不可继承）
InitializeProcThreadAttributeList / UpdateProcThreadAttribute(PROC_THREAD_ATTRIBUTE_JOB_LIST)
STARTUPINFOEXW + STARTFIELDS(STARTF_USESTDHANDLES)
CreateProcessW(EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
```

为什么必须走这条路：标准库 `subprocess` 的 `lpAttributeList` 只认 `handle_list`，
传 job 属性会直接报错，所以只能自己调 `CreateProcessW`。

Job 句柄只由宿主持有、**不给子进程继承**，这样 `KILL_ON_JOB_CLOSE` 才会在宿主死亡、
句柄归零时真正触发（上一轮“宿主入 job”失败正是因为子进程继承了句柄，永不归零）。

Observer 侧已切换：`_spawn_observer_child` 优先走 `spawn_in_job`，原生路径不可用时
降级回 asyncio 并写警告（不让观察器因为平台差异起不来）。`_ChildHandle` 把两种后端
统一成 `stdout.read / stderr.read / stdin.write+drain / wait / kill / pid`，observer.py
其余逻辑没有改动。

## 2. 已验证

| 验证 | 结果 |
|---|---|
| `spawn_in_job` 起进程、读 stdout、返回 job 句柄 | 通过 |
| `terminate_job` 一次收掉子进程 + 孙进程 | 通过（两个 pid 都消失） |
| 宿主被 `taskkill /F`（不带 `/T`）后子进程与孙进程死亡 | **通过** |
| Observer 在原生 spawn 下正常跑起来（子进程写出 pid 标记） | 通过 |
| observer / ack / 执行守卫 / 崩溃残留 / 命令工具 回归 | 137 passed |

关键证据是宿主强杀那条：`taskkill /PID <host> /F` 不带 `/T`，不会替被测代码杀树，
子进程与孙进程确实由 job 关闭回收。

## 3. 未完成（不得当作已通过）

1. **1000 次强杀注入没跑完。** 注入器 `core/scripts/kill_injection.py` 已写好，
   单轮逻辑可用，但批量循环存在卡住：连续两次跑到工具超时（700s / 900s），
   40 轮应当在 90 秒内结束。已定位嫌疑在每轮的 `host.wait()` 与 `taskkill` 返回时序上，
   **尚未修复，也未取得 1000 次的数据**。
   另外两次早期版本是**空转通过**（观察器没起来，0 孤儿毫无意义），已加
   `child_processes_observed` 计数防止再次误判。
2. **7 项历史基线失败没修。** 本轮没有动它们，仍在原始 HEAD 上复现同样的 7 个失败。
3. **24 小时 soak 是上一个提交跑的**，不覆盖本轮的原生 spawn 改动，按你的要求
   没有干扰它，但它不能作为本轮验收依据；新提交需要重新做针对性验证和长跑。
4. **副作用可终止性审查只做了一半**：已明确命令与工具出口两个边界可强制终止、
   纯 Python 直写文件和网络请求不能打断（详见上一轮报告第 9 节），但还没有
   针对“取消后仍在写文件/发请求”的专门用例。

## 4. 结论

机制对了，证据还不齐。按你给的门槛：**1000 次强杀 0 孤儿 + 7 项基线修复 + 新提交的长跑**，
三条都没达成之前不合并、不 push。
