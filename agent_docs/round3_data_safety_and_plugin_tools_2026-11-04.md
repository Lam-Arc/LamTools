# 2026-11-04 第三轮：数据安全、插件工具的合法执行与终态收敛

## 一、卸载丢数据：结论是没有丢，测试断的是退役布局

`PluginHost.uninstall` 的流程是：`prepare_data`（把插件目录里的 `data/` 迁到 `<state.path.parent>/plugin-data/<name>`，并把原位置换成链接）→ 删代码目录 → 只有 `keep_data=False` 才删 durable 数据。

实测（`keep_data=True`）：

```
data_path .../plugin-data/diary
inline before True
plugin dir exists False
inline after False          <- 旧断言看的这一处
shared after True           <- 数据在这里，内容 "kept"
discover []
```

`remove_tree` 对符号链接/junction 走 `unlink`/`rmdir`，不会跟进数据目录。所以字节没有丢，是测试仍在断言退役的“就地 data 目录”。

处理：

- `test_plugin_system_core.py` / `test_plugin_system_operations.py` 改为断言 durable 位置；
- 追加重装边界：卸载保留数据后重新安装同一插件，`data/entry.txt` 仍能读回（这条断言直接覆盖“卸载→重装”这个用户路径）。

## 二、插件后端被错误阻断：真因是 auto_allow 声明没有落到操作等级

证据链：`demo_tool`（工具清单写 `permission: auto_allow`）经工具盒执行时被拦，`prepare_call` 给出的判定是

```
tier=ask_user level=3 auto_approve_level=1 reason=操作等级 3 超过免问线 1，需要确认
```

`level=3` 来自 `operation_level()` 对“未注册操作”的默认值，而清单里的 `auto_allow` 只登记进 `manifest_tool_permissions`，对等级路径没有任何影响。于是：

- 只读档（能力上限 1）里，这类工具被“超过能力上限”直接拦掉；
- 其它档里，每次调用都要用户点一次确认。

这解释了 Soak 之外最影响日常使用的插件体验问题。修复点在插件工具进入工具盒的位置（一次性规则，不做第二套状态）：

> 声明 `auto_allow` 且没有显式 `operation_level` 的插件工具按 1 级登记；显式等级优先（含更严格值），`ask_user` 与 `hard_block` 仍走原来的保守默认。

没有放宽边界：写入类插件工具应当声明 `ask_user` 或显式等级；`auto_allow` 本来就是“不用问”的声明。修复后 `test_bundled_plugin_executes_via_core_assembly` 一并转绿，`test_default_toolbox` / `test_operation_permission_levels` / `test_subagent_prompt` 共 120 项无回归。

## 三、中风险项：区分设计语义与过期测试

| 项 | 判定 | 处理 |
| --- | --- | --- |
| 委派汇总纪律 | 真实缺陷（文案在改写中丢失） | 委派指南补回“报告已确认事实、剩余不确定性与下一步” |
| 手动压缩边界 | 过期测试 | 边界是“最后一条被摘要的行”，保留尾部逐字发送；断言改为边界=首个保留行-1，且有效视图=摘要+保留行 |
| 压缩触发来源 | 设计语义 | 产品明确“优先真实 usage、允许一拍延迟、不与估算取最大值”；测试改为断言来源 `usage`，并把触发阈值放在估算与真实值之间，真正证明真实计数能触发 |
| Goal Dispatch 未调用 | 过期测试（补丁打在再导出上） | `queue_dispatch` 在函数内从 `runtime_tasks` 导入，补丁改打在 `runtime_tasks` |
| 工具清单数量 | 过期计数 | 基础集 21（`mcp` 取代退役的 `mcp_activate`），装配后 35（新增 `network_download`） |

## 四、仍开放（有证据，按风险排列）

1. **Kernel 压缩拟合失败会让整轮失败**（`test_kernel.py` 3 条 `failed` vs `done`）：拟合策略全部无法把摘要压到目标值后，本轮以失败结束。行为本身是保守的（不发送超窗请求），但是否应降级为“best-effort 继续”需要产品判定，本轮不改。
2. **恢复+附件后 UI 事件为空**（`test_resume_supplement_guidance.py` 2 条）：模型侧断言全过（每个请求恰好一条附件消息、角色与位置正确），但同一套事件读取在“带附件恢复”时拿到 0 条事件，而纯文本恢复拿到 19 条。属于转写可见性，待下一轮定位。
3. `test_channel_runner_services.py`：该失败时压缩没有失败（`compacted/not_needed`）。
4. `test_turn_steer_revision.py`：`stale_target` 未回到 `idle`。
5. `test_system_prompt_english.py`：系统提示词里混入非英文。

## 五、全量

见第六节（源码绑定 + SHA 头）。
## 六、本轮全量与验收起点

冻结 SHA：`9342c86c`（源码绑定 + `--expect-sha` 校验，`round3b_full.log`）

```
57 failed, 4225 passed, 9 skipped
```

起点是 79 failed / 4203 passed，本轮净修好 22 条，其中真实产品缺陷 3 类：

1. 插件工具声明与操作等级脱节（`auto_allow` / `ask_user` 都落到 3 级）；
2. 禁用/硬拦截分支借用“自动放行”的理由；
3. 委派汇总纪律在文案改写中丢失。

新增失败 0 条。`test_plugin_system_singleton` 在两次全量里一次失败一次通过，单文件重复运行 6 次全过，属缓存隔离的抖动，记为不稳定用例而非产品缺陷。

## 七、权限到等级的完整映射（本轮收口）

原来只有 `hard_block` 在等级路径上有效，其余声明全部落到“未注册操作=3 级”：

| 声明 | 等级 | 行为 |
| --- | --- | --- |
| `hard_block` | 0 | 直接阻断 |
| `auto_allow` | 1 | 不问，受能力档位约束 |
| `ask_user` | 2 | 默认问；用户显式选 auto 才不问 |
| 显式 `operation_level` | 按声明 | 优先于上表 |
| 3 级 | 保留 | 只给真正破坏性操作 |

收益：只读档里，声明为只读用途的插件工具不再被“超过能力上限”拦掉；auto 模式下，委派出去的 workflow 工具不再把子代理停在一次用户已经放弃的确认上。没有放宽硬拦截与能力档位。

## 八、仍未关闭（下一轮入口）

- Kernel 压缩拟合失败即整轮失败（3 条 `failed` vs `done`），需要产品判定是否降级为 best-effort。
- 恢复+附件时 UI 事件为 0（模型侧断言全过）。
- `channel_runner_services`（该失败时压缩未失败）、`turn_steer_revision`（stale 未回 idle）、`system_prompt_english`（混入非英文）。
- 环境前置：Office 4 条（缺 manifest / LibreOffice 超时）、Network 4+3 条（缺 Rust 控制器 / 本地 5172 未起）、workflow WSL 超时 1 条。
- 契约漂移余项：`review_*` 4、`core_cli` 3、`update_installer` 2、`artifact_store` 2、`core_runtime_persistence` 2、`plugin_system_skills` 2、`tool_result_model_evidence` 2、`backend_deep_split` 1、其余各 1。

## 九、验收状态

- 全量：已完成，57 条全部归类（真实缺陷 / 契约漂移 / 环境前置）。
- 强杀注入：20 轮 PASS（0 孤儿），1000 轮已启动，结果下一轮读取。
- 崩溃恢复 ×100、24h Soak：未在本次执行，需在冻结 SHA 上重跑（Soak 口径已改为只统计本轮）。
