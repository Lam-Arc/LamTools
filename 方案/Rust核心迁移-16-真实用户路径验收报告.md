# Rust 核心迁移 16：手机端真实任务闭环验收

日期：2026-11-04
分支：`sunday/m3-isolated-core`
验证环境：Android 模拟器 `sunday_tablet`（2560x1600 / Android 16 / x86_64），本机 Ollama `qwen2.5:3b`
诚实标记：全部证据来自 AVD，**没有真机验证**

## 一句话结论

普通用户目前**还不能**在手机上完成一次真实任务。链路已经从"点了没反应"推进到"消息发出、模型真实回复、事件真实送达界面"，但停在最后一层：**共享 UI 的内容渲染只认 `core/runItem` 投影，Rust 核发的是另一套 `item/*` 事件**，所以消息、审批卡片都进不了界面。

## 这轮真正修掉的东西

### 1. 自动化工具本身不可信（先修的，因为它在骗人）

- `uiautomator dump` 失败时会保留上一次的 XML，脚本照读，坐标全错，每次点击都落在旧位置，看起来和功能坏掉一模一样。改为先删文件、要求成功行、失败重试三次、仍失败则报错。
- 输入框内容读不到：webview 的 textarea 在无障碍树里是空 `EditText`，真实值在同位置 `TextView` 里。改为按输入框边界找重叠文本节点，并取面积最大的 `EditText`（侧栏搜索框也是 `EditText` 且排在前面）。
- 逐字符删除要 10 秒，改为一次 `input tap` 批量 160 个删除键。
- 系统代理河蟹掉 adb 转发的 9222 端口：CDP 客户端全部绕过代理，WebSocket 显式 `proxy=None`。

### 2. 侧栏永远显示"项目下没有会话"

`core/ui/src/projects/types.ts` 归组只看 `session.metadata.work_root` 是否等于项目目录。Rust 核返回的是 `project_id`、没有 `metadata`，于是每个项目下的会话列表恒为空，而 `/sessions` 明明返回了数据。改为优先按 `project_id` 归属，目录仅作回退。

### 3. 模型配置在手机上完全不可用

设置 → 模型页说的是桌面 Python 核的 `config.*` 语言（供应商、模型、模型组），Rust 核一个都没实现，界面报 `method not found: config.provider.create`，发送按钮因此永远禁用，且只弹一条 8 秒后消失的提示。

新增 `core/android-host/src-tauri/src/config_rpc.rs`，把这套语言翻译到 Rust 的单供应商配置：

- 读：`config.providers.list` / `config.providers.status` / `config.models.list` / `config.model_groups.list` / `config.notices.drain` / `config.models.usage`
- 写：`config.provider.create|update|delete`、`config.models.upsert`、`config.model.create_with_provider`、`config.models.set_default`、`config.models.delete`
- 探测：`config.providers.probe` 真的向端点请求 `/models`，成功才设置 `confirm_endpoint`

安全约束沿用 `settings.rs`：改地址即刻作废端点批准，密钥只进不出，探测的客户端禁止重定向、短超时、不重试。

结果：设置页能看到供应商，界面从"模型"变成真实模型名 `qwen2.5:3b`，发送按钮可用。

**已知取舍**：这层是单供应商、单模型。用户添加第二个供应商会覆盖第一个，不像桌面端能并存。这是真实降级，没有包装成等价。

### 4. `thread/resume` 只回事件列表，UI 拿不到快照基线

`Session::handle` 会把内部 `_events` 字段剥掉，于是 `thread/resume` 实际返回 `{thread_id}` 而已。UI 需要 `snapshot`（要有 `thread_id` 与 `snapshot_seq`）才能建立状态，再叠加 `events`。没有基线，历史不显示，之后每一个实时事件都被丢弃。

改为返回 `snapshot` + `events`（`snapshot_seq` 故意为 0，否则客户端会跳过这次刚要投递的事件）。`thread/read` 同步修正。

### 5. 模型端点探测能力

`core/sunday-core/crates/sunday-llm/src/lib.rs` 新增 `list_models`，给"检测连接"用真实回答，而不是存一个布尔值假装连上了。

## 设备上确实发生的事（有据可查）

```
Ollama: 16:36:30 | 200 | 1.719s | POST /v1/chat/completions     ← 模型真的被调用
core_event -> turn/accepted seq=9
core_event -> item/tool_prepared seq=10
core_event -> item/approval_request seq=11
```

设备库 `journal_events` 也留着记录：seq 2-6 依次是 `run_started`、`model_started`、`model_completed`、`tool_prepared`、`approval_requested`。

也就是说：**模型收到了任务，规划了工具调用，停在了等待审批**。这些都在后端真实发生了。

## 断在哪里

界面上看不到任何消息、任何审批卡片。原因不是渲染 bug，是两套事件语言：

- 共享 UI 的内容渲染入口是 `applyCoreRunItemEvent`，只处理 `method === 'core/runItem'`，按 `payload.kind` 分派：`status`、`message`、`approval_request`、`approval_response`、`tool_result`、`usage`、`interaction_update`。
- Rust 核的 `translate` 发的是 `turn/accepted`、`item/tool_prepared`、`item/approval_request`、`turn/model_completed` 这类方法名。
- `applyAppEvent` 只认 `turn/accepted`、`turn/started`、`item/started`、`queue/*`，其余一律原样返回快照。

所以事件虽然跨过了 IPC、进了浏览器，却没有落到任何 item 上。会话在 UI 眼里是空的，那句"芜湖，我来帮忙咯!"是预制的空会话问候语，不是模型输出。

**要补的是 Rust 侧的一层投影适配**：把 runner 的事件写成 `core/runItem` 信封（`kind` + `item_id` + `turn_id` + `payload`），覆盖 `message`、`approval_request`、`tool_result`、`status` 四类。这是一层真实适配，不是补渲染补丁。

## 未完成

1. 上面这层投影适配（本阶段的关键阻塞）。
2. 审批通过后工具是否真的执行、`notes.md` 是否落盘，因此无法验证。
3. 关闭应用重开后历史与任务状态的恢复，无法验证。
4. 异常中断后"结果未知不自动重试"的界面表达，无法验证。
5. SAF 文件授权、附件、文件预览。
6. `web_fetch` 未接入工具注册（沿用上轮结论）。

## 已通过的真实检查

- `cargo test --lib`（android-host）：18 passed（新增 4 项 config_rpc 测试）
- `cargo test -p sunday-host`：全部通过，含 `_events` 不泄漏的合同测试与安全负面测试
- `cargo fmt --all -- --check`：干净
- `python scripts/android_project.py all --debug --target x86_64`：APK 构建 + 三项签名/产物校验通过，装机成功
- `vue-tsc`：改动文件无新增类型错误（仓库另有 17 项既有错误，与本次无关）

## 回滚方式

本分支上的提交可用 `git revert <sha>` 单独回退。若只要回到上一版可用 APK，重装上一轮产物即可，设备数据（`core.db`、`projects.json`）不受影响。

## 数据安全

`data/core.db` 本轮未读写，大小与 mtime 与前几轮一致。
