# 2026-11-04 第二轮：源码绑定、成员流停顿、Windows Job 结案

## 一、测试源码绑定（硬约束）

`core/tests/conftest.py` 新增会话级守卫，在收集之前执行：

| 检查 | 不通过时 |
| --- | --- |
| `lamtools_core` 包必须位于本检出 `core/src` 下 | 退出码 2，打印期望路径/实际路径/正确的调用命令 |
| `--expect-sha <sha>` 提供时，HEAD 必须以它开头 | 退出码 2 |
| `core/src` 有未提交改动（除非 `--allow-dirty`） | 退出码 2，列出脏文件 |
| 通过 | 会话头打印 `lamtools source: ... @ <sha> (clean)` |

实测四种情形：

```
污染（不加 PYTHONPATH）        -> Exit: 测试源码未绑定本检出 … 退出码=2
SHA 不匹配 (--expect-sha deadbeef) -> Exit: 提交 SHA 不匹配：期望 deadbeef，当前 40338aaef2b7 … 退出码=2
脏 core/src                    -> Exit: core/src 有未提交改动 … 退出码=2
干净                           -> lamtools source: ...\core\src\lamtools_core @ 40338aaef2b7 (clean)
```

正式验收用这条命令，SHA 对不上就根本没有测试结果：

```
cd .worktrees/reliable-base
PYTHONPATH="E:/LamTools/.worktrees/reliable-base/core/src" \
  python -m pytest core/tests -q --expect-sha <冻结的sha>
```

历史混合基线（87/4195 等）全部作废，本分支的真实基线以本文件第五节为准。

## 二、可靠性工具入库

`core/scripts/` 原来整目录被 gitignore。改为只忽略 `__pycache__`，三个工具入库：

- `core/scripts/reliability_soak.py`（长跑 + 崩溃注入 + 结算）
- `core/scripts/kill_injection.py`（强杀注入，统计孤儿）
- `core/scripts/arrange_soak.py`
- 新增 `core/scripts/job_reclaim_probe.py`（本文件第三节的实验）

soak 与 kill_injection 启动先 `_ensure_path()`，随后 `_report_source()` 打印绑定源码与提交；加载到别的检出直接退出，不出结果。

## 三、Windows Job：之前的结论是错的

上一轮我写“嵌套 job 下 Windows 不执行 KILL_ON_JOB_CLOSE”，微软文档不支持这个说法，实测也不支持。用 `job_reclaim_probe.py` 重新测量，每组都是：新建 kill-on-close job → 拉起子进程（sleep 600）→ 硬杀父进程 → 等 3 秒 → 查子进程是否存活。五种情形：

| 场景 | 父进程在 job 内 | 子进程在 job 内 | KILL_ON_JOB_CLOSE | 结果 |
| --- | --- | --- | --- | --- |
| nested / 创建期 JOB_LIST | 是 | 是 | 是 | 已回收 |
| nested / 创建期 JOB_LIST + 管道 | 是 | 是 | 是 | 已回收 |
| nested / 创建后 Assign | 是 | 是 | 是 | 已回收 |
| detached / 创建期 JOB_LIST | 否 | 是 | 是 | 已回收 |
| detached / 创建后 Assign | 否 | 是 | 是 | 已回收 |

补充测量：`CREATE_BREAKAWAY_FROM_JOB` 在外层 job 下返回拒绝访问，所以 detached 场景改用 WMI 创建进程（父进程是服务，天然在 job 之外），并确认 `host_in_job=False` 才计入。

强杀注入 `kill_injection.py --iterations 20` 的结果：

```
valid=20 invalid=0 timeouts=0 host_errors=0 orphans=0 orphan_children=0 orphan_grandchildren=0
[result] PASS（taskkill /F，只杀宿主，不带 /T）
```

结论：

- 回收机制在普通启动与嵌套 job 下都成立，句柄继承（管道变体）也没有破坏它。
- 之前“关闭 job 句柄后子进程仍存活”的探针结论作废：那个探针只关了本进程的一个句柄，并不是最后一个句柄；真正的回收语义要在宿主进程整体消失时观察，本次实验正是这样测的。
- 因此不存在“受影响的真实用户启动场景”。Soak 里那 11 个是计量口径把别的轮次残留算进来了（已改为只统计本轮目录）；soak24 自身是否还漏了 1 个，等本轮重跑 24h Soak 给出答案，在那之前不结案。

## 四、成员派发后模型流无事件：是测试替身缺陷

沿真实调用链取证：

1. 成员内核确实派发了请求：`[kernel:_run] step=0 dispatching model request sid=...:sub:writer`，随后 `[kernel:_stream_model] starting stream`。
2. 客户端对象与主代理同一个：`ShallowThinkingClient`，`enabled=False`，走直通分支；内层就是注入的替身（同一个对象 id）。
3. 替身抛出 `AttributeError: 'WritingSubAgentLLM' object has no attribute '_child_step_by_shape'`，位置在替身 `stream` 的第一行之后，所以内核拿不到任何事件。

根因是我上一轮改测试的补丁只迁移了一半：父分支的形状映射落在 `ApprovalSubAgentLLM`，子分支的形状映射落在 `WritingSubAgentLLM`，而两个类的构造函数各缺一半。它是我自己引入的测试缺陷，不是产品缺陷，产品侧的派发、流包装、审批和落盘都正常。

修复方式：抽一个 `_ShapeDrivenScript` mixin，两个替身共用同一套形状推进与状态初始化，避免再次半迁移。修复后 `test_core_sub_agent_runner.py` 33 项全绿（12.7 秒），被委派的成员真实写出文件并回传。

## 五、本轮全量

见 `round2_full.log`（绑定源码、绑定 SHA 头）。第一节的守卫生效后，这个数字才代表本分支。

## 六、下一步

按真实风险收敛剩余簇：`plugin_system_*`、`review_*`、`test_kernel`、`workflow`、`core_cli`、`goal_dispatch`、`bundled_plugins`；`office`、`network` 属环境前置，先做环境准备再判定。
