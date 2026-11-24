# Sunday Connect — C1 连接可靠性实施报告

- 日期：2026-11-23
- 分支：`sunday/m3-isolated-core`
- 依据：`方案/Sunday-Connect-PRD-V1.0.md`、`方案/Sunday-Connect-01-现状复核.md`
- 范围：PRD C1（配对安全、状态准确、无感恢复、消息可靠性）以及 C1 依赖的审计/RTT 可观测性
- 结论：C1 的 P0 项已落地并通过本机测试与真实双进程 P0 验收；C2/C3/C4 未开始。

## 1. 配对安全（PRD 3.1 / 4.2）

### 1.1 扫码不再等于授权

- `core/p2p/src/gate.rs` 新增 `Admission::Pending` 与 `CODE_PAIRING_PENDING`：
  有效的一次性票只登记“待确认”，不写可信名单，也不允许任何远程调用。
- `core/p2p/src/pair.rs` 的 `PairingGrants` 新增 `pending` 记录（按 nonce 保存设备 id/名字/申请时间/过期时间）：
  - 同一张票不能被第二台设备拿去申请；
  - 电脑确认/拒绝后，票才被消费；
  - 待确认记录落盘，进程重启仍然存在；
  - 过期申请在 `prune` 时自动作废，不能复活。
- `core/p2p/src/link.rs` 握手前重读 `p2p-pairing.json`，宿主确认/拒绝后下一次连接立即生效。

### 1.2 电脑端确认/拒绝

- CLI 新增 `sunday-p2p pending / confirm / reject`（`core/p2p/src/bin/cli.rs`）：
  - `pending` 列出待确认设备；
  - `confirm` 写可信名单并消费票；
  - `reject` 消费票并把设备记入撤销名单。
- 桌面宿主新增命令 `p2p_pending` / `p2p_confirm_device` / `p2p_reject_device`（`core/desktop/src-tauri/src/p2p_host.rs`、`main.rs`）
  并通过启动 `sunday-p2p confirm/reject` 改同一份文件。
- 设备页新增“待确认设备”区块，可确认/拒绝（`core/ui/src/components/RemoteConnectionPanel.vue`）；
  `p2p_status`/`p2p-state` 带 `pending[]`。

### 1.3 手机等待体验

- `p2p_connect` 在等待确认时把原因原样带回；界面识别后显示“等待电脑确认”，
  每 2.5 秒用同一张票自动重试（最多 60 次），电脑确认后自动接上。
- 纯函数 `isAwaitingApproval` 在 `core/ui/src/app/remoteReconnect.ts`，有单测。

### 1.4 验收

- `scripts/verify-p2p-p0.ps1` 已改为两步配对，并在真实两进程上跑通：
  - 首次扫码 `DIAL FAILED`，且待确认设备不在可信名单；
  - `pending` 能看到申请；
  - `confirm` 后同一张票可以配对并拿到 `sunday1:` 地址票；
  - 同一张票第二台设备被拒；
  - 撤销对活跃连接当场生效。

## 2. 状态准确（PRD 3.2 / 3.3）

- 手机宿主 `core/android-host/src-tauri/src/p2p_bridge.rs`：
  - 拨号成功后先发 `initialize`，再 `ping`；两者都成功才算业务可用；
  - `p2p_status` 返回 `view / reason / layers{transport,device,core,session}`；
  - Core 挂掉或探测失败时显示 `degraded`，不是“已连接”；
  - 断线、主动断开、新连接都会把业务层结论归零。
- 桌面原本的四层判定保持不变，新增 `rttMs`。
- 界面（`core-app/main-android.ts`、`transport/remoteTransport.ts`）只按 `isUsable(status)` 选择远程通道，
  不再用裸 `connected` 猜；`RemoteTransport.connect()` 也不再无条件报已连接。
- 远程请求超时：`Client::call_with_timeout` + `p2p_call(timeoutMs)`，
  超时只结束这一次等待，连接与对端状态不变。

## 3. 无感恢复（PRD 3.2）

- 手机保存 `sunday1:` 地址票：`p2p_connect` 返回 `resume`，
  `saveConnectedDevice` 把当前票、重连票、设备清单一起换成地址票；
  切换设备时两份票一起换（`core/ui/src/app/remoteSession.ts`）。
- 修复设备清单识别：地址票可以解析出节点 id，配对过的电脑会真正出现在清单里。
- RPC 桥重建后补 `thread/resume`（`core/p2p/src/rpc.rs`），
  断线期间的 journal 事件不再只依赖界面自己重新打开会话。
- 重试用尽后 `RemoteTransport` 落到 `disconnected`，不再永久停在“正在连接”。

## 4. 消息可靠性（PRD 4.3）

- 重放白名单收紧为显式只读方法（`core/ui/src/transport/remoteCodec.ts`）：
  `config.provider.create`、`config.model.*`、`settings.update` 等写操作不再被当成只读重放；
  补了 `config.*` 读方法、`workspace.search`、附件/会话读方法。
- 新增本地待确认账本 `core/ui/src/appServer/pendingWrites.ts`：
  - `turn/start` / `turn/resume` 在“回执丢失”时落 localStorage；
  - 默认 TTL 24 小时，读取时自动清理；
  - `turn/started` 或 RPC 回执到达后结算；
  - `core/ui/src/appServer/store.ts` 已接入。
- 重发仍复用同一个 `client_message_id`，由 Core 去重；超时不等于失败。

## 5. 可观测与审计（PRD 4.1 / 4.2）

- RTT：`core/p2p/src/link.rs` 从 iroh 当前选中路径读取 `Path::rtt()`，
  `Client`/`ServerLink` 暴露 `rtt_ms()`；状态通道 `Path` 事件新增 `rtt_ms`；
  桌面 `p2p_status.rttMs`、手机 `p2p_status.rttMs`、设备页“连接详情 → 延迟”都已接。
- 审计：桌面宿主追加写 `%APPDATA%/Sunday/p2p/p2p-audit.jsonl`，
  记录票据过期时间、设备连接/断开、会话恢复、文件接收、撤销/允许、配对确认/拒绝；
  不记录可用的配对票全文。

### 5.1 手机端稳定性与反馈（2026-11-23 追加）

- **状态主动推送**：手机宿主每 2 秒算一次四层快照，只有真的变了才 `emit('p2p-state')`；
  设置页/设备页不再等下一次操作才发现 Core 挂了。Core 降级后每 10 秒用一次
  `settings.get` 真探测，恢复了自动回到 ready。
- **后台保活**：新增 `SundayConnectionService`（前台服务）+ `ConnectionServiceBridge` +
  Tauri 命令 `connection_service_set`。它只把进程留在前台，不建立第二条连接；
  低优先级通知，用户关掉开关就停止，下次启动也不会自己回来。
- **简单入口**：设备连接页加入设置分区（`设置 → 设备连接`），手机不再只能靠隐藏入口；
  页面里有“后台保持连接”开关与一句说明。
- **默认值**：后台保活默认开；只有用户明确关掉才持久化为关。
- 这部分对应 PRD 3.2/3.3/4.6 的“减少无故断连、状态可见、用户可选”。

## 6. 主要改动文件

- `core/p2p/src/pair.rs`
- `core/p2p/src/gate.rs`
- `core/p2p/src/link.rs`
- `core/p2p/src/rpc.rs`
- `core/p2p/src/bin/cli.rs`
- `core/p2p-status/src/lib.rs`
- `core/desktop/src-tauri/src/p2p_host.rs`
- `core/desktop/src-tauri/src/main.rs`
- `core/android-host/src-tauri/src/p2p_bridge.rs`
- `core/android-host/src-tauri/src/android_jni.rs`
- `core/android-host/src-tauri/src/lib.rs`
- `core/android-host/android-src/com/lamtools/sunday/core/SundayConnectionService.kt`
- `core/android-host/android-src/com/lamtools/sunday/core/ConnectionServiceBridge.kt`
- `core/android-host/scripts/android_project.py`
- `core/ui/src/components/CoreSettings.vue`
- `core/ui/src/components/settingsSections.ts`
- `core/ui/src/app/remoteSession.ts`
- `core/ui/src/app/remoteReconnect.ts`
- `core/ui/src/appServer/pendingWrites.ts`
- `core/ui/src/appServer/store.ts`
- `core/ui/src/transport/remoteCodec.ts`
- `core/ui/src/transport/remoteTransport.ts`
- `core/ui/src/components/RemoteConnectionPanel.vue`
- `core/ui/src/core-app/main-android.ts`
- `scripts/verify-p2p-p0.ps1`、`verify-p2p-p1.ps1`、`verify-p2p-p2.ps1`

## 7. 验证结果

```text
cargo test --manifest-path core/p2p/Cargo.toml --lib
  75 passed

cargo test --manifest-path core/p2p-status/Cargo.toml
  5 passed

cargo test --manifest-path core/desktop/src-tauri/Cargo.toml --bin Sunday p2p_host
  18 passed

cargo test --manifest-path core/android-host/src-tauri/Cargo.toml --lib
  2 passed

npx vitest run tests/remote-panel-rtt.test.ts tests/remote-panel-pending.test.ts \
  tests/remote-reconnect.test.ts tests/remote-session.test.ts \
  tests/remote-codec.test.ts tests/pending-writes.test.ts --maxWorkers=1
  6 files / 20 tests passed

powershell -File scripts/verify-p2p-p0.ps1
  17 项全 PASS（真实两进程：待确认 → 确认 → 配对 → 重连 → 撤权）

powershell -File scripts/verify-p2p-p1.ps1
  22 项全 PASS（真实两进程：四层齐了才 connected / Core 挂了降级 / Core 回来重新 initialize / 隧道断了自动重连 / 长断线提示）

powershell -File scripts/verify-p2p-p2.ps1
  17 项全 PASS（真实两进程：路径显示 / 状态通道 / 重连先对账再重发 / 同键不重写）
```

模拟器（x86_64）验收：

- `npm run build:android` 成功；
- `python core/android-host/scripts/android_project.py all --debug --target x86_64` 成功，
  产物 `core/android-host/src-tauri/gen/android/app/build/outputs/apk/universal/debug/app-universal-debug.apk`（329066 KB）；
- `adb install -r` 成功，应用启动正常；`设置 → 设备连接` 页面可见，
  含“本机 / 扫码连接电脑 / 粘贴票据 / 后台保持连接”；
- ActivityManager 记录 `SundayConnectionService` 已在 `TOP` 状态启动，无 JNI 链接错误。

未在本轮执行：

- Android 真机（前后台、休眠、网络切换、扫码）；
- 干净 Windows 安装包实跑、24 小时资源曲线、受限 NAT / 第三方 VPN；
- 文件双向/续传/校验、能力权限、任务接力、虚拟局域网。

## 8. 与 PRD 的对照

| PRD 条目 | 当前状态 |
| --- | --- |
| 3.1 首次配对（二维码/身份/一次性/待确认） | 已完成；待确认 + 电脑确认 + 手机自动重试 |
| 3.2 日常自动连接 | 地址票、自动重连、短断线静默、Core 重启恢复已接；手机总开关仍未做 |
| 3.3 连接状态 | 等待授权、正在连接、已连接、正在恢复、离线已有；权限受限随 C2 能力权限 |
| 4.1 智能选路 | 直连/中继/路径迁移沿用 Iroh；RTT 已显示；速率未做 |
| 4.2 可信设备与权限 | 身份/命名/配对/解绑/撤权/审计已有；能力分级与密钥轮换在 C2 |
| 4.3 可靠消息 | 读重放、幂等、超时未知、待确认账本/TTL 已接；通用消息信封与离线队列在 C2/C4 |
| 4.4 文件与数据 | 未开始（手机侧未接、无双向/续传/校验/限速） |
| 4.5 任务与会话接力 | 未开始（同一 Core 会话可远程操作，但没有接力元数据） |
| 4.6 Android 后台连接 | 未开始（无连接类前台服务、无网络回调/诊断） |
| §5 虚拟局域网 | 未开始（EasyTier 评估待做） |
| §6 AI 通讯预留 | 传输层分离已完成；统一消息对象/离线同步未做 |
| §7 量化验收 | 未建立采集；本轮只补了 RTT 与审计 |

## 9. 待决策

1. **能力权限粒度**：C2 是先只拦高风险能力（终端、键鼠、屏幕、工作区外文件），还是直接做完整能力表。
2. **文件方向**：先做手机→桌面发送（复用现有 `send`），还是先做桌面→手机的 `ask` 帧与手机接收循环。
3. **Android 后台连接**：是否提供“持续连接”前台服务开关，以及通知权限被拒时的降级文案。
4. **C3 虚拟局域网**：EasyTier 的许可、Android VPN 权限、与 Iroh/现有代理的兼容性需要单独评估后再决定是否接入。

## 10. 已知风险

- 桌面 Core 默认无令牌：本机任意进程可绕过隧道直接调 Core；这是既有安全缺口，未在本轮改动。
- RTT 只在路径事件时更新，不是每秒刷新；设备页显示的是最近一次测量。
- 审计是本地 JSONL，没有轮转/查询界面；长期运行需要补轮转策略。
- 手机端自动重试最多约 2.5 分钟，票过期后会停下并提示重新扫码。
- 模拟器上没有真实电脑配对，设备页显示“还没有配对的电脑”；真实配对/后台保活通知需接电脑复验。
- x86_64 运行时资产是从已安装 APK 取回的本机调试产物，位于 `core/android-runtime/tools/out/x86_64`，未提交。
