
---

# 2026-11-04 收敛轮次一：子代理回传链路与父级唤醒复核

## 一、先说一个影响全部历史结论的测量错误

可编辑安装 `_editable_impl_lamtools_core.pth` 里写的是主工作区路径 `E:\LamTools\core\src`。之前所有从工作树 `.worktrees/reliable-base/core` 发起的 pytest，加载的都是**主工作区另一条分支**的 `lamtools_core`，只有测试文件来自本分支。

正确调用（从仓库根目录，显式指定源码）：

```
cd .worktrees/reliable-base
PYTHONPATH="E:/LamTools/.worktrees/reliable-base/core/src" python -m pytest core/tests -q
```

按此重跑的基线：**81 failed / 4201 passed / 9 skipped**（826 秒）。旧数字（87/4195）作废。

## 二、A 子代理 message 回传

链路本身是通的，断点在测试：

1. `ApprovalSubAgentLLM` 用裸计数器推进脚本，一次重试就把脚本推到下一格，断言失败后分支改变，回传链从未被真正走到。改为按请求形状推进，重试重放同一答案。
2. 断言写成「最后一条消息是身份块」。产品侧既定契约是「身份块是最后一条 **user** 消息，wake 与上下文变更通知可以跟在后面」，并由 `test_base_agent_prompt_translation.py::test_member_wake_tail_stays_after_mutable_runtime_context` 明确锁定。断言改为真实契约。
3. 另一条用例只等 1 秒就去读子代理写的文件，且「是否空闲」在消息启动回合之前就已经成立。改为等待真实前置条件，超时 15 秒并给出可读失败原因。

修复后该用例全绿，`sub_agent.message` → `supervisor.child_message` → `sub_agent_mailbox` → 父级下一回合读到内容，整条闭环有断言覆盖。

## 三、B 空闲父代理唤醒

五项全部已实现，不是回归：

| 项 | 位置 |
| --- | --- |
| 持久化信箱写入 | `sub_agent_supervisor.child_message` → `_mail(child_to_parent)`，落 `sub_agent_mailbox` |
| 父代理空闲判断 | `memory_resume_supervisor._wake_member_thread` 的五道守卫：活跃回合、用户取消、暂停、排队用户消息、唤醒预算 |
| 完成事件触发 | `_record_member_event(member_finished)` → `sub_agent_events` → `list_threads_with_pending_member_wakes` |
| 新回合启动 | `_start_continuation(origin="member_wake", prompt=member_wake_prompt(...))` |
| 信箱消费与 ACK 去重 | 回合开始 `drain_parent_mailbox` + `acknowledge_parent_mailbox`；事件侧 `mark_member_events_delivered` 只在回合真正启动后认领；`child_message` 按 provider message id 去重 |

运行中、空闲、已取消三场景由 `test_memory_resume_supervisor.py` 覆盖（全部通过）。其中一条断言把 wake 历史的元数据整字典写死，而内核会给每条追加消息盖到达步数，改为只校验有意义的三项。

## 四、24h Soak 的唯一失败项

`orphan_observer_processes: 11` 这个数字不是本轮泄漏量。原实现按命令行通配 `observer-work` 在**整机**上统计，把 crash100d / crash100e 等更早轮次的残留一并计入。已改为只统计本轮目录下的观察器。

底层机制另有事实需要记录：`spawn_in_job` 的 `PROC_THREAD_ATTRIBUTE_JOB_LIST` 与创建后的 `AssignProcessToJobObject` 都能确认子进程进入 job、`KILL_ON_JOB_CLOSE` 位也确实置上，但父进程被 `/F` 强杀后子进程仍存活。原因是当前进程本身处在 LamTools 的 job 内，运行时创建的 job 是嵌套 job，嵌套场景下 Windows 不执行这条限制。“内层进程被强杀、外层宿主仍存活”不是用户路径；用户关闭应用时外层 job 关闭会连带回收。按已知限制记录，不在本轮扩架构。

## 五、本轮仍未关闭

- `test_core_agent_operation_forwards_sub_agent_file_tool_and_handoff`：成员回合卡在 `runner.run` 等模型流，成员派发了请求但拿不到第一个事件。已确认不是计时问题（15 秒仍无进展），待下一轮定位。
- 其余簇：`plugin_system_*`（7）、`review_*`（4）、`test_kernel`（5）、`workflow`（4）、`office`（4，环境前置）、`network`（4，缺 Rust 控制器）、`core_cli`（3）、`goal_dispatch`（3）、`bundled_plugins`（3）。

## 六、提交

```
b12ebdf7 test(subagent,member): replay retries by request shape and follow the real ordering contract
f0e51465 test(subagent): wait for the real handoff and advertise the tools under test
```

两条都只改测试，未动运行时行为。
