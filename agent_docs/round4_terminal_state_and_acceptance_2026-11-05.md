# 2026-11-05 第四轮：压缩终态、恢复附件、环境前置与验收

## 一、压缩终态：安全降级优先，无法安全继续则明确失败

产品规则（用户裁定）：

1. 先复用现有机制尝试安全恢复：拟合器已有的摘要压缩、按步丢弃、最小摘要；
2. 仍然装不进目标预算时，先看**这次请求本身**是否还在窗口内 —— 在窗口内就跳过压缩、原样继续，不丢任何上下文；
3. 请求本身超窗才停止本次调用，报明确原因，保留历史与任务状态，支持重试；
4. 不发送超窗请求、不静默丢上下文、不把失败伪装成成功。

实现只动了一处判定（`kernel/loop.py` 里 `result.status == "failed"` 分支），没有新增状态机：

```
current_tokens = calibrated_tokens(estimate(request))
planned_tokens = max(before_tokens, current_tokens)   # 权威计数与本地估算取更保守者
if planned_tokens <= limit_tokens:   → 跳过压缩，记录 skipped_over_budget，继续
else:                                 → 抛出明确失败（over_limit 时附“未发送超窗请求、历史与任务状态保留，可重试”）
```

`max(...)` 是关键：不能用本地估算单方面判定“还装得下”，否则会放一个真正超窗的请求出去。

失败路径的文案保持分流：预算超限用控制器给出的“failed to fit within limit: X > Y tokens”并追加重试说明；模型调用失败保留原有措辞（`Context compaction failed: Model call failed after N attempts...`），两类失败仍然可以区分。

证据：`test_kernel.py` 164 项通过；两条“必须明确失败”的用例（`test_compaction_model_failure_stops_run_without_success_event`、`test_compaction_fails_clearly_when_preserved_context_exceeds_limit`）保持通过。余 1 条 `test_auto_compaction_does_not_resurface_fitter_dropped_step_in_same_or_next_run` 仍未通过：它的替身伪造了一份与真实估算不一致的压缩结果（after=20 while 真实装配 ~2k），在“最终预算再校验”下必然失败，属夹具与真实预算不兼容，不是产品行为问题，记为未关闭夹具项。

## 二、恢复+附件：不是 UI 事件缺失，是附件契约变了

沿数据链逐层确认（探针实测，三次请求）：

- 附件**没有**丢失在 UI：更大的问题原本被误读成“UI 事件为 0 条”，实际失败断言是模型侧“每个请求恰好一条附件消息”。
- 探针显示：恢复后的三个请求里，附件内容（文件正文）出现 0 次 —— 因为附件早已改为**只传绝对路径**（`user:“不再直接上传附件本身到请求，而且替换为一个绝对路径在用户消息中”`），模型用 `read_file` 按需读取。
- 因此模型侧确实收到了附件引用（`note.txt | 绝对路径 | id=...`），只是不含文件正文。测试仍在断言旧契约“正文内联”。

处理：按指针契约重写断言（恰好一条引用消息、role=user、包含文件名与绝对路径、**不包含**文件正文；带文本时同一消息里含用户文本），UI 侧“只显示一条引导、不把模型内容块写进 UI 元数据”的断言保持不变。该文件 6 项全绿。没有新增事件写入，也没有为了显示重复落库。

## 三、环境前置：用现有机制准备，缺什么说什么

- Network：用仓库自带的构建脚本同一条途径构建控制器（`cargo build --locked --manifest-path .../controller/Cargo.toml`，release 脚本会额外构建界面并下载引擎），再跑插件自带的 `engine_install.py` 准备 aria2 1.37.0 与 mihomo v1.19.33。之后 `test_network_live_rpc`、`test_network_download_tool` 转绿。
- 仍失败 5 条（`test_network_exploration` 4 + `test_network_config` 1）需要界面产物与真实转发链路，属可选组件集成，**未验证**，不计为通过。
- Office：本机有 LibreOffice 与路径，但 4 条 CLI 用例仍报计数不符（`assert 3 == 0` 等），同样属可选组件（渲染器/清单）集成，**未验证**，不计为通过。
- 这些失败不计入核心运行时失败；同时也不会被标记为通过。

## 四、singleton 缓存用例

`test_plugin_system_singleton::test_discover_cache_reuses_results_until_roots_change` 在全量里偶发失败、单文件连跑 6 次全过，属缓存隔离/顺序敏感，不是产品缺陷。本轮不改产品，只记录。

## 五、冻结与验收

候选 SHA `51cd0109`（core/src 与最终 SHA 一致，见提交后的 `git diff --stat`）。同一版本全量：

```
52 failed, 4230 passed, 9 skipped   (14:42)
```

与上一冻结版 `9342c86c`（57 failed / 4225 passed）相比：修好 7 条，新增 2 条，且这 2 条（`test_parallelizes_only_whitelisted_tool_names`、`test_http_total_deadline_expires_despite_continuous_data`）单独运行全过，是满载下的计时抖动。

52 条分类：核心缺陷 1 类（压缩夹具，已记）、契约/夹具漂移约 30 条、可选组件环境 9 条（Office 4 + Network 5）、计时抖动 2 条、其余为单项契约漂移。

强杀注入：`9342c86c` 上 1000/1000 通过（0 孤儿、0 超时、0 主机错误）。新 SHA 上的 1000 次与 100 次崩溃恢复、24h Soak 见验收记录。
## 十、更正：压缩终态不需要“跳过压缩继续”这条分支

收尾核对时按用户要求检查“保守窗口校验是否会重新引入重复压缩”，写了一条针对性测试（请求介于触发线与上限之间、摘要压不进目标预算、两步运行）。测试结果推翻了我上一轮的假设：

- 拟合器可以把摘要截断到任意短，它的下限是“系统前缀 + 必须保留的尾部”，而不是摘要本身；
- 因此“拟合器装不下”当且仅当“前缀+保留尾部本身超过上限”，而这两部分都包含在原请求里 —— 也就是说，**拟合器失败时请求本身必然已超窗**；
- 结论：上一轮加的“请求还在窗口内就跳过压缩继续”分支实际不可达，只会带来一个新状态字段和一个运行级标记。

按“不为不可达场景增加机制”处理：

- 删除跳过分支、运行级标记常量、成功路径上的清理代码，以及那条测试；
- 保留既有的安全降级（摘要压缩 → 按步丢弃 → 最小摘要）与明确失败（文案含“未发送超窗请求、历史与任务状态保留、可重试”）；
- 复测 `test_kernel + test_context_compaction + test_compaction_architecture` 共 248 项通过，余 1 条仍是已知的夹具不兼容项。

双计数逻辑现状（核对结论）：

- 测量：`context_measurement` 优先使用真实 usage，缺失时用估算兜底，两者不取最大值（这是既定设计，允许一拍延迟）；
- 窗口校验：失败分支只用控制器给出的预算结论，不再做第二套“是否还在窗口内”的判断，因此不会重复压缩，也不会把可继续的情况判成失败；
- 重复压缩风险：成功压缩后历史变短，下一步的占用自然低于触发线；只有请求重新变大才会再次触发，这是预期行为。
