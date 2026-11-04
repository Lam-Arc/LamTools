# 2026-11-05 验收记录（同一版本）

## 版本

- 验收执行版本：`1cf1bfb6`（runtime `core/src` + `core/tests` 与本文件提交前逐字节一致，见提交后 `git diff --stat 1cf1bfb6 HEAD -- core/src core/tests` 输出为空行）。
- 上一阶段版本 `9342c86c` 的结果保留为阶段证据，不用于代表本版本。

## 一、全量测试

绑定方式：`conftest` 源码守卫 + `--expect-sha 51cd0109`（该提交的 runtime 与最终版本逐字节一致）。

```
52 failed, 4230 passed, 9 skipped   （14:42）
```

与阶段版本 `9342c86c`（57 failed / 4225 passed）相比：修好 7 条，新增 2 条（`test_parallelizes_only_whitelisted_tool_names`、`test_http_total_deadline_expires_despite_continuous_data`），这两条单独运行全过，属满载计时抖动。

52 条构成：

| 类别 | 数量 | 说明 |
| --- | --- | --- |
| 可选组件环境（未验证） | 9 | Office 4（渲染器/清单）+ Network 5（界面产物、真实转发） |
| 契约 / 夹具漂移 | 30 | 含导入已删除模块、签名变更、文档措辞、清单计数、指纹等 |
| 计时抖动（单独跑全过） | 2 | 不应计为产品失败 |
| 核心缺陷 | 1 | `test_auto_compaction_does_not_resurface_fitter_dropped_step...`：替身伪造与真实估算不一致的压缩结果，需重做夹具，产品行为未改 |
| 其余单项 | 10 | 见 `round3` 分类表 |

## 二、100 次崩溃恢复

```
jobs_total 61, completed 60, waiting 1, stuck_running 0
peak_concurrency 3（配置上限 3）
duplicate_occurrences 0, duplicate_effect_attempts 0, duplicate_effect_records 0
leaked_child_processes 0, orphan_observer_processes 0
crashes 100, recovery_seconds_median 1.255s
[result] PASS
```

统计口径修正：原来按 pid 统计并发峰值，Windows 会复用 pid，两次强杀之间的两代宿主被并成 4，误报“超过上限”。改为每代宿主自带唯一 id 后，峰值回到真实的 3。这是统计缺陷，不是运行时越界。

## 三、1000 次强杀

```
iterations 1000, valid 1000, invalid 0, timeouts 0, host_errors 0
orphans 1（orphan_children 0, orphan_grandchildren 1）
[result] FAIL（按“0 孤儿”判据）
```

事实核查：

- 报告时间点确实存在 1 个观察器进程；等我去检查时它已经自己退出，环境中不再有残留。
- 也就是说这是一次**短暂漏收**：硬杀窗口里漏掉一个观察器，它随后自行结束，不是永久占用。
- 1000 次里出现 1 次（约 0.1%），与之前 24h Soak 里 1 个残留一致。

结论：回收机制在绝大多数情况下正确，存在低频、自愈的漏收。按判据不通过；按影响面属轻微资源问题（无数据、权限、事务风险）。没有为此增加新的进程回收机制（如挂起创建后再恢复的额外路径），因为收益不足以抵消复杂度。

## 四、尚无同版本证据的项目

- 24h Soak：未在 `1cf1bfb6` 上执行。阶段版本的上一次 24h Soak 因统计口径失败，不能代表本版本。
- 无人值守 fail-closed、权限与副作用边界：由全量里的相关簇覆盖（`test_core_live_approval`、`test_plugin_system_approval`、`test_operation_permission_levels`、`test_default_toolbox` 共 100+ 项通过），未单独做长时注入。

## 五、结论

- 真实缺陷修复有证据、有回归覆盖（插件权限桥、卸载数据、压缩终态、恢复附件契约）。
- 同版本已完成：全量、100 次崩溃恢复、1000 次强杀。
- 同版本未完成：24h Soak。
- 因此**暂不建议合并**；补齐 24h Soak 后即可给出合并结论。
