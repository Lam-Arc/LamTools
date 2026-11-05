# 可靠性整治分支合并到主线：记录与验证

日期：2026-11-05
集成分支：`sunday/reliable-merge`（工作树 `E:\LamTools\.worktrees\merge-reliable`）
被合并分支：`sunday/reliable-base`（`c5479fcf`，72 个提交）

## 一、结论

可靠性整治工作已经合并到主线开发线的顶端，合并结果可被主线直接快进。合并后同版本全量回归的失败条数与基线完全一致（50 条），没有引入新的代码缺陷，也没有删除主线任何文件。

## 二、目标分支与分叉情况

仓库里有三条互不相连的历史：

| 分支 | 顶端 | 与本次合并的关系 |
| --- | --- | --- |
| `sunday/m16-projection` | `675b6530` | 主线开发线顶端，本次合并的目标 |
| `sunday/m3-isolated-core` | `97d18bbd` | `m16` 的祖先，落后 23 个提交 |
| `sunday/reliable-base` | `c5479fcf` | 可靠性整治线 |

关键事实：

- 本地 `main` 停在 `dd54b7fd`（0.2.6，2026-08-17），与当前开发线没有共同祖先，不是活跃主线。
- `sunday/m16-projection` 是 `sunday/m3-isolated-core` 的直系后代（合并基 `97d18bbd`，`m3` 独有 0 个提交，`m16` 独有 23 个），所以目标定为 `m16` 而不是 `m3`。
- `sunday/reliable-base` 与主线没有共同祖先（`git merge-base` 返回空）。
- 内容上的真实基线是 `39dd5c26`（`release: Sunday 0.3.37`）。它只在 `reliable-base` 历史里，但 `git diff 39dd5c26 <主线>` 在 `core/tests` 上为空、在 `core/src` 上只差 `__init__.py` 一行版本号，因此可以当作内容基线使用。

## 三、为什么不能直接 git merge 原分支

两分支无共同祖先时，git 会把“双方都新增”的文件按对方版本重写。实测 `git diff HEAD sunday/reliable-base` 为 233 文件、+11300/−42148，其中大量删除是主线独有的新文档。所以直接 `git merge sunday/reliable-base` 会退掉主线文件，不可用。

## 四、实际合并方式

1. 从主线顶端 `ede46609` 建集成分支 `sunday/reliable-merge`。
2. 用 `git cherry-pick -x 39dd5c26..c5479fcf` 把 71 个提交逐个应用到该分支。
3. 结果：71 个提交全部应用成功，零冲突。

零冲突不是巧合。合并前先算过两边改动的文件集合：

- `39dd5c26..c5479fcf` 改动 96 个文件（37 个 `core/src`、41 个 `core/tests`、其余文档）。
- `39dd5c26..主线` 改动 146 个文件（`core/src` 只有 `__init__.py`）。
- 交集只有 `.gitignore` 一个文件，`core/src` 与 `core/tests` 交集为 0。

`.gitignore` 的改动是 `reliable-base` 有意把 `core/scripts/` 重新纳入版本管理（改为只忽略 `__pycache__`），按 `reliable-base` 的版本保留。

## 五、合并结果核对

| 核对项 | 结果 |
| --- | --- |
| 提交数 | 71 个全部应用，另加 1 个用例修复、1 个合并提交 |
| 相对主线改动的文件 | 96 个，与 `reliable-base` 的改动面完全一致 |
| 主线文件是否被删除 | 0 个 |
| `core/src` + `core/tests` 与 `reliable-base` 的差异 | 仅 `__init__.py` 版本号，保留主线较新的 `0.3.38`（`reliable-base` 为 `0.3.37`） |
| 合并提交是否改动被测试代码 | 否，`git diff 4e987805 HEAD -- core/src core/tests` 为 0 行 |

## 六、回归验证

绑定方式：`PYTHONPATH` 指向集成工作树的 `core/src`（系统里 `lamtools_core` 的可编辑安装指向主工作区，不覆盖会测到主工作区源码），加 `--expect-sha` 绑定提交。

| 版本 | 结果 | 耗时 |
| --- | --- | --- |
| 基线 `1b68bd30` | 50 failed / 4232 passed / 9 skipped | — |
| 合并结果 `4e987805` | 50 failed / 4232 passed / 9 skipped | 634.59s |

条数完全一致。失败集合有两处互换，不是新增回归：

- 多出 2 条环境前置：`test_network_download_tool.py::test_unified_download_active_aria_accepts_route_updates`（本机无 `aria2c`，`which aria2c` 为空）、`test_network_live_rpc.py::test_running_host_exposes_network_page_and_one_controller`（无已配置模型，报 `model id is required`）。两条单独复跑稳定失败，属环境缺失。
- 少 2 条已知抖动：`test_kernel.py::TestKernelParallelToolWhitelist::test_parallelizes_only_whitelisted_tool_names`、`test_release_plugin_market.py::test_long_stderr_cannot_block_rpc`。这两条在基线里就被归为计时抖动与 stderr 洪泛，本次通过，属抖动另一侧。

## 七、合并过程中修掉的一个用例缺陷

首次全量（`2fbbaf76`）多出 1 条失败：`test_arrange_acceptance_metrics.py::test_1000_jobs_with_capacity_three_never_exceeds_peak`，报“只有 998 个任务最终 completed”。

单跑复现为间歇失败（3 次里 1 次），根因在用例自身而不是调度器：`ArrangeRunner.stop()` 会取消仍在跑的任务（`arrange.py:1229`），而用例一看到执行器被进入 1000 次就立刻停 runner，此时最后几个任务还在写终态，被取消后状态不是 `completed`。

修法：停 runner 之前先等到所有任务进入终态（复用 `arrange._TERMINAL_STATUSES`），让断言测的是调度器，而不是用例自己的收尾竞态。修后连续 5 次全通过，全量里也通过。提交 `4e987805`。

## 八、一次误操作与恢复

第一次尝试在已存在的 `.worktrees/integration`（分支 `sunday/selfdev-acceptance`）里执行 cherry-pick，因为 `git worktree add` 因目录已存在而失败，命令却继续在该目录里跑。结果把 11 个可靠性提交落到了那条 plugin-host 分支上，并在第 12 个提交处冲突停下。

处理：`git cherry-pick --abort` 后 `git reset --hard 0df51e3b`，该分支与工作树回到操作前的干净状态（`git status` 0 项，`CHERRY_PICK_HEAD` 不存在）。没有丢失任何用户改动。之后改用新目录 `.worktrees/merge-reliable` 重建。

## 九、剩余 50 条失败的定性

与基线一致，未因合并变化：环境前置 13（Network 5、Office 4、本地 RPC 端口 4）、插件侧脚本相对导入 4、契约/夹具漂移约 30、压缩夹具 1、进程后端 stderr 洪泛 1、计时抖动 2。没有数据损坏、没有安全越界、没有核心运行时阻塞。

## 十、落地方式

`sunday/m16-projection` 已是 `75e1e35e` 的祖先，落地是一次快进：

```
git -C .worktrees/m16 merge --ff-only sunday/reliable-merge
```

未执行该快进，原因：`.worktrees/m16` 里有另一条正在进行的改动（`core/android-host/src-tauri/Cargo.toml` 未提交），且在本次合并期间该分支连续前进了两个提交（`616f0a55`、`675b6530`）。移动这条分支需要先确认那边的会话空闲。

没有 push，没有发布。
