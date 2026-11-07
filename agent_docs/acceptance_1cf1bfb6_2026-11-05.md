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

## 十一、收尾核对（最终版本 `1b68bd30`）

### 版本与全量

- 最终 SHA：`1b68bd30`（压缩终态去掉不可达分支后的版本）。
- 同版本全量：**50 failed / 4232 passed / 9 skipped**（14:26），绑定 `--expect-sha 1b68bd30`。
- 与上一版本 `51cd0109`（52/4230）相比：**新增 0 条**，消失 2 条，正好是之前那两条满载计时抖动（singleton 缓存、http 截止时间）。

### 核对一：1000 次强杀里的 1 次漏收

结论修正（上一版记录写“自行退出”是错的）：漏收的是**孙进程**（测试观察器自己起的 sleeper），不是观察器本身；它没有自行退出，是强杀工具在统计后立刻用 `taskkill /T /F` 清掉的。

- 机制：该轮命中了观察器创建的原生路径失败后的降级路径（先 spawn、后登记 job），宿主在登记完成前被杀，于是观察器及其孙进程落在 job 之外。
- 残留：报告时 1 个进程；现在 0 个进程、0 个 pid 文件；只留下测试用的 mark 文件（不是进程）。
- 用户风险：该进程不打开 `core.db`、不写用户数据，只通过 stdio 与已死的宿主通信；影响仅是“多一个空闲 python 进程直到应用重启”。
- 处置：按用户决定不加新的回收机制；原子创建路径（占绝大多数）没有这个窗口，降级路径只在原生创建瞬时失败时出现，1000 次里 1 次。

### 核对二：剩余 50 条失败的定性

按风险分三类核对：

1. **数据损坏：无。** 没有一条失败涉及写入/删除用户数据；最接近的 `test_artifact_store_v2`、`test_core_runtime_persistence` 都是元数据形状/签名断言，不触碰落盘内容。
2. **安全越界：无。** 权限与审批相关的簇全部通过（`test_operation_permission_levels`、`test_default_toolbox`、`test_core_live_approval`、`test_subagent_prompt` 的禁止委派、`test_plugin_lifecycle` 的缺依赖拦截）。唯一相关的失败 `test_active_plugin_agent_sets_the_gate_stance` 是替身缺 `prompt_waterfall` 属性，属夹具，不是闸门被绕过。
3. **核心运行时阻塞：无。** 1000 次强杀与 100 次崩溃恢复都没有卡死/重复执行/泄漏；内核循环、子代理、检查点相关簇均通过。

余下失败的实际构成：

| 类别 | 数量 | 说明 |
| --- | --- | --- |
| 环境前置（未验证） | 13 | Network 5（后端操作未注册、界面产物）、Office 4（渲染器/清单）、本地 RPC 端口 4（core_cli 3 + outline 1，`ConnectionRefused 127.0.0.1:5172`） |
| 插件/发布侧脚本自身导入失败 | 4 | `review_*`：相对导入在独立脚本模式下失败，属插件仓脚本环境 |
| 契约/夹具漂移 | 约 30 | 工具改名（`mcp_activate`→`mcp`）、签名新增参数、文档措辞、清单计数、指纹、页面标题等 |
| 压缩夹具不兼容 | 1 | `test_auto_compaction_does_not_resurface_fitter_dropped_step`：替身伪造的压缩结果与真实预算校验不一致 |
| 进程后端健壮性 | 1 | `test_long_stderr_cannot_block_rpc`：插件进程后端被 7MB stderr 洪泛时自身 RPC 超时，范围限于该后端，不影响内核循环 |
| 计时抖动 | 2 | 上一版出现、本版消失，单独跑全过 |

两项需要如实标注的“非阻断但存在”：

- 进程后端在极端 stderr 洪泛下会拖慢自己的 RPC（不阻塞主循环）。
- 观察器降级创建路径存在极窄窗口，1000 次里漏收 1 个孙进程（工具会立即清理）。

### 核对三：压缩的双计数与重复压缩

- 测量：`context_measurement` 优先真实 usage，缺失时用估算兜底，两者不取最大值（既定设计，允许一拍延迟）。
- 窗口校验：上一轮加的“请求还在窗口内就跳过压缩”分支经测试证明**不可达**（拟合器可把摘要截到前缀+保留尾部，装不下即等于请求已超窗），已整段删除，连同运行级标记与成功路径清理代码。
- 重复压缩：删除该分支后不存在第二套判定；成功压缩后历史变短，下一步占用自然低于触发线，只有请求重新变大才再次触发，属预期。
- 复测：`test_kernel + test_context_compaction + test_compaction_architecture` 248 项通过，余 1 条为上面的夹具不兼容项。

### 合并建议

**建议合并 `1b68bd30`。**

- 真实缺陷已修且有回归覆盖：插件权限声明与等级脱节、卸载数据的错误断言、压缩终态（安全降级 + 明确失败）、恢复附件契约。
- 同版本可靠性证据：全量 50/4232（0 新增失败）、100 次崩溃恢复 PASS、1000 次强杀 999/1000 干净且漏收进程被工具即时清理。
- 已知限制（不阻断）：进程后端 stderr 洪泛下的自身 RPC 超时；观察器降级创建路径的极窄漏收窗口；压缩夹具一项待重做；13 条可选组件环境用例未验证。
- 未 push、未 merge、未发布，等待授权。
