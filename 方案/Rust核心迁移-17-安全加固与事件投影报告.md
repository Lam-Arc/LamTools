# Rust 核心迁移 17：探测安全加固与事件投影

日期：2026-11-04
分支：`sunday/m16-projection`（从已推送的 `97d18bbd` 起，worktree `.worktrees/m16`）
验证环境：Android 模拟器 `sunday_tablet`，本机 Ollama `qwen2.5:3b`
诚实标记：全部证据来自 AVD，没有真机验证

## 一句话结论

两件事都做了，但只完成一件半：**探测漏洞已修并有真实 socket 测试**；**事件投影已实现，界面第一次真正画出助手消息和审批卡片**；**点击批准仍然到不了后端，文件没有落盘**，所以"用户能在手机上完成首次文件任务"这个验收标准，本轮没有达成。

## 一、探测安全漏洞（已完成）

修的是 `config_rpc.rs::probe` 与 `sunday_llm`：原来直接把存储的 API Key 发给配置里的地址，改一下地址就把密钥送给了没人批准过的主机。

现在按三步走，每一步在代码里都看得见：

1. `provider::admit` **离线**判端点（协议、主机、传输策略）。公网明文 HTTP、非法地址在这一步就被拒，一个 socket 都不会打开。
2. **无凭据探测**。不发 `Authorization`，所以无论对方是谁都花不掉秘密。
3. 只有第 2 步证明这个地址真的有人应答，才写入 `confirm_endpoint`，之后才允许第二个请求带密钥。

批准因此是"地址可达"挣来的，不是按钮声明的；改地址会立刻作废批准（`write_provider` 里）。前端把按钮藏起来不能满足这条，规则长在打开 socket 的地方。

`sunday_llm::list_models` 改成了 `probe_endpoint`，返回 `Models/Unauthorized/Status` 三态。这个区分是必需的：401 证明有服务在应答，连接失败什么都不证明，把两者都压成 `Err` 正是上一版出事的根源。

错误信息统一走 `redact_secret`，密钥不会出现在回显里。

**真实 socket 负向测试**（`config_rpc.rs` 测试模块，起真监听口记录请求头）：

- `an_unapproved_endpoint_receives_no_key_on_the_first_contact`：首个请求无 `Authorization`，批准之后第二个才有
- `editing_the_address_stops_the_key_from_following_it`：换地址后新主机只收到无凭据请求
- `an_unreachable_endpoint_is_never_approved`：不应答的地址不会被批准
- `a_public_plain_http_endpoint_is_refused_without_any_request`：公网明文在联网前被拒
- `a_refused_key_is_reported_without_leaking_it`：401 照实报，密钥不外泄

## 二、事件投影（已实现，界面已出卡）

共享 UI 只认 `core/runItem`，按 `payload.kind` 分派；Rust 核发的是 `item/tool_prepared`、`turn/model_completed` 这类自有词汇。两边不是一套语言，所以事件全都到了、全都匹配不上，会话看着永远是空的。

新增 `core/android-host/src-tauri/src/projection.rs`，在 host 的协议边界翻译，规则取自桌面核的 `event/runtime_projection.py`，这样两个核描述同一件事说的是同一套话：

- `item_id` 稳定可推导：一次工具调用从审批到执行共用同一个 id，审批卡更新自己那一行，不会长出新卡
- `event_id` 由日志 seq 派生：resume 重放同一条事实得到同一个 id，客户端的去重集合直接吃掉副本
- 回合身份向前传递：`run_started` 报一次，同线程后续 item 都归它
- 历史与实时走同一个函数（`IpcSink::event` 与 `core_rpc` 的 `project_events`）

`payload.type` 用的是 UI 的词汇（`userMessage` / `agentMessage` / `dynamicToolCall` / `serverRequest` / `status`），因为 `normalizeCoreItemDisplayType` 让 payload.type 优先于内部映射。

投影需要的原料原本不在事件里，已补进核心：工具名与参数（`ToolPrepared`）、结果正文（`ToolSucceeded/Failed`）、模型文本（`ModelCompleted`）、用户原话（`command_accepted` 的 payload）。补的是字段，不改协议形状。

**8 项投影单测**覆盖：用户消息、无文本不产气泡、审批卡挂到工具行且带工具名、工具结果闭合同一行、等待裁决不算完成、重放身份一致、文本不重复输出、内部事件不外泄。

## 三、设备上的真实证据

界面首次真实渲染出：

```
ASSISTANT
Greetings! How can I assist you today?

审批 · 待处理
需要确认：approval
等待确认后执行工具调用
  批准执行  允许后端继续执行这个工具调用。
  拒绝执行  不执行这个工具调用，本轮停在等待点。
  其他处理方式

需要你确认，共 2 项 · 第 1 / 2 项
```

日志侧同时可见翻译在跑：

```
core_event -> core/runItem kind=status seq=2
core_event -> core/runItem kind=tool_call seq=5
core_event -> core/runItem kind=approval_request seq=6
core_event -> core/runItem kind=message seq=8
core_event -> core/runItem kind=approval_request seq=11
```

应答链路是通的：`qwen2.5:3b` 回了 200，`approvals` 表里有 `pending` 记录。

## 四、没打通的断点

点"批准执行"之后：**没有任何新事件，`workspace/` 仍然为空。**

已排除的：
- 后端不认识 UI 的决策词——`app_server.rs` 第 536 行起已把 `approve_once`/`other_guidance` 归一化，不是这里
- 端点/模型侧——模型调用本身成功过
- 页面报错——劫持 `console.error` 后点击，数组为空

已修复但尚未在同一轮验证的：审批请求 id 之前只放在 payload 顶层，而按钮读 `metadata.request_id`，现在两处都放。改了之后重新打包过，但随后会话被旧审批占住，没能跑一次干净的"新建会话 → 发送 → 批准"。

还没查的：`approval/respond` 发出后是被 transport 挂住，还是 `respondApproval` 根本没被调用；以及旧会话残留的审批与新建会话的关系。

## 五、构建环境：三个真实缺陷（顺手修了）

隔离 worktree 里连续失败七次，每次原因都不同，其中三个是项目/工具的缺陷而不是环境的：

1. `tauri android init` 生成 `BuildTask.kt` 时把 node 写成 `node.EXE`，Gradle 认不出这个扩展，拼成 `node.EXE.bat` 后启动失败。脚本现在构建前把这个路径改成 `node`，交给 PATH 解析。
2. 生成的 Android 工程在 worktree 里不完整，`:app` 找不到 `TauriActivity`。最终解法是复用主工作区里已验证的生成工程（`gen/android` 是生成产物，不含源码）。
3. `scripts/android_ui.py` 读输入框内容只找重叠的 `TextView`，而 webview 有时把值直接挂在 `EditText` 上，导致"明明输入成功却报空"。已改为先读自身、再找重叠节点。
4. `scripts/android_cdp.py` 把 `@webview_devtools_remote_*` 原样丢给 `localabstract:`，adb 接受转发但每个连接都被断开。已去掉前导 `@`。
5. `android_project.py` 增加 `ANDROID_IGNORE_TAURI_VERSION_MISMATCH=1` 开关，对应 CLI 官方的 `--ignore-version-mismatches`，默认关闭。

另外：`core/ui/dist-android-app` 里我曾放过一个占位 index.html，导致第一次装机界面只显示 "stub"。第二轮先 `npm run build:android` 再打包才正确。

## 六、未完成

1. **审批点击 → 工具执行 → 文件落盘**（本阶段核心阻塞）
2. 文件预览器里看到 `notes.md` 内容
3. 关闭重启后会话与文件的恢复
4. 重复投递、断线重连不产生重复消息/重复执行
5. 进程中途死亡后未知副作用不自动重放
6. 用户消息气泡在同一轮里的最终确认（载荷已修，未在同一次干净会话里验证）

## 七、工程结果

- `cargo test --lib`（android-host）：**31 passed / 0 failed**，其中 config_rpc 9 项（含 3 条真实 socket 负向测试）、projection 8 项
- `cargo fmt --all -- --check`：干净
- APK 构建 + 三项产物校验通过，装机成功
- 远端 CI：本轮未跑

提交：`2279ad21`

## 八、回滚

`git revert 2279ad21` 可整体回退本轮改动。worktree 在 `.worktrees/m16`，用完可 `git worktree remove .worktrees/m16`。

主工作区那 100 多个来源不明的未提交改动全程未碰。

## 九、数据安全

`data/core.db` 未读写。设备上的 `core.db` 只做只读复制用于核对事件与审批记录。
