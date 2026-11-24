> 更新（2026-11-23）：C1 已实施，见 `方案/Sunday-Connect-02-C1实施报告.md`。本文件保留复核时的原始判断。

# Sunday Connect — C0 现状复核

- 日期：2026-11-23
- 分支：`sunday/m3-isolated-core`
- 提交：`8108509c release: Sunday 0.3.43`
- 方法：通读当前代码 + 关键路径交叉核对 + 本机可执行测试；未做真机与干净系统验收。
- 结论口径：本文件只判定“现在有什么、缺什么”，不把历史文档的完成声明当证据。

## 一、总评

底座已经成立，不是从零开始：Iroh 传输、一次性配对票、可信设备与即时撤权、隧道上的 Core RPC/事件、二进制附件透传、四层连接状态、桌面宿主起停与打包、单文件互传引擎、设备页与互传面板都已落地并有测试。

与 PRD 的差距主要不是“重写传输”，而是补五层：

1. **配对缺少电脑端确认**。当前扫码即信任，违反 PRD 3.1 第 3–4 步和 4.2“配对授权不等于授予全部远程控制权限”。
2. **手机没有可持续的重连凭据**。手机只记住 5 分钟配对票，没有落 `sunday1:` 地址票，重启或切设备超过 5 分钟后只能重扫。
3. **手机端“已连接”只等于隧道活着**。没有 PC Core 探测与业务握手，无法满足 3.2/3.3“真实业务可用才显示已连接”。
4. **消息可靠层只覆盖了部分读写**。`client_message_id` 覆盖 turn/queue，但没有通用消息信封、TTL、持久待确认队列；重放白名单还把配置写操作当成只读。
5. **权限、审计、可观测性、Android 后台、双向/可续传文件未完成**。这些是 C1–C3 的主体。

### 1.1 两个术语与现状的偏差

- **“Android Lite Agent”**：当前 Android 不是轻量 Agent。`core/android-runtime/README.md` 明确写的是“the shipping Python core — the same `core/src/lamtools_core` the desktop app runs”，手机在 proot 里跑完整 Python Core。若 PRD 的“轻量 Agent”是目标架构，这是一次独立迁移，不在现有连接底座里。
- **“Sunday Relay”**：当前传输用的是 Iroh 的 `presets::N0` 公共 relay（或 `SUNDAY_P2P_RELAY(S)` 配的自定义 Iroh relay），没有经过 `core/remote/relay`。后者是旧自建 relay，构建/打包/CI 均无引用。PRD §5 说“不是替换 Sunday Relay”之前，需要先定义这里的 Sunday Relay 指哪一个。

## 二、PRD §2 审查对象

状态：✅ 通过 · ◐ 部分 · ✗ 未做 · ⚠ 与 PRD 冲突

| 对象 | 现状（证据） | 结论 |
| --- | --- | --- |
| Iroh 集成 | `core/p2p/src/identity.rs` 用 `presets::N0` 建 endpoint、ALPN `sunday/p2p/1`；`dialable_addr` 出票前等 relay；`link.rs` 用 `path_events` 报 direct/relay；本机真实双进程互传测试已跑通。 | ✅ 接入完整 |
| 配对机制 | `pair.rs` 的 `sunday2:` 票带节点签名、过期时间、一次性 nonce，≤300 秒；`gate.rs` 拒绝陌生设备；`p2p-pairing.json` 落盘防进程重启重放。**但没有“待确认设备”状态，扫到有效票立即写可信名单。** | ◐ 安全底座通过；确认流程与 PRD 冲突 |
| 打包发布 | `release.yml`、`scripts/package.ps1`、`Sunday.iss`、`build-installer.ps1` 都把 `sunday-p2p.exe` 列为必需；`p2p_host::binary()` 有三级查找；退出时 `stop()` 杀子进程。 | ✅ 代码与 CI 通过；干净系统未实测 |
| Android 客户端 | `main-android.ts` 有 20 秒首连预算、3→30 秒退避常驻重连、`visibilitychange` 触发、`p2p-progress=lost` 即重连；`p2p_bridge.rs` 有拨号串行与 generation 防旧连接误报。**没有 ConnectivityManager/NetworkCallback，也没有连接类前台服务；`LifecycleBridge` 只打日志。** | ◐ 恢复逻辑有；系统级后台与网络回调缺失 |
| Core 生命周期 | 桌面 `p2p_host.rs` 用 `/api/health` 1.5 秒 TTL 探测；Core 换端口时重启传输进程；`CoreRpc` 死桥重建；`Layers` 四层判定。手机端不探测 PC Core，只看 `Client::is_alive()`。 | ◐ 桌面强，手机弱 |
| 设备撤权 | `TrustStore.revoked` + 文件时间戳重读；`ServerLink::serve` 每条调用前复核、每秒复核；拒绝时先发 `device_revoked` 再断开。桌面设备页可撤销/重新允许。 | ✅ 功能通过；审计缺失 |
| 消息协议 | 隧道 `call/reply/error/event` 按 id 配对；Core journal 有 `seq`、`thread/resume` 回放、`thread/gap`；turn/queue 有 `client_message_id` 去重与 acceptance waiter。**没有通用消息信封、TTL、持久待确认队列；`initialize.lastSeenSeq` 不触发回放。** | ◐ 部分 |
| 文件传输 | `transfer.rs` 有 4 个 `file/*` method、256 KiB 分块、8 GiB 上限、`.part` 原子改名、重名不覆盖、进度/取消、未授权先拒；本机真实双进程测试通过。**没有校验和、暂停/续传、带宽限制；只有拨号方发、服务端收；手机宿主未接。** | ◐ 单文件最小闭环 |
| 性能 | 没有建连/重连耗时、RTT、吞吐、资源占用的采集或界面；`p2p-status` 只有路径与阶段。 | ✗ 可观测性未做 |
| 安全 | 已配对设备拿到的是**整个本机 Core** 的 RPC/REST 能力；没有能力分级、路径 ACL、审计。桌面 Core 默认无令牌，本机任意进程可直连。身份私钥是普通文件（Android 在应用私有目录，Windows 在 APPDATA）。 | ⚠ 与 PRD 4.2/4.4 冲突 |

## 三、用户交互（PRD §3）

### 3.1 首次配对

| 步骤 | 现状 | 结论 |
| --- | --- | --- |
| 1 电脑生成短时二维码 | `p2p_ticket` → `sunday-p2p serve` 出 `sunday2:`；UI 显示二维码与倒计时 | ✅ |
| 2 手机扫码 | `p2p_scan` 走相机预览解码，填入票据 | ✅ |
| 3 建立身份验证、电脑显示待确认设备 | 节点身份在 QUIC 握手中验证；**没有“待确认”状态，也没有待确认列表** | ◐ / ✗ 第 4 步缺 |
| 4 用户确认配对 | 不存在确认动作；有效票即写可信名单 | ✗ |
| 5 自动选路 | Iroh 直连优先、中继回退；`PEER ... path=` 可见 | ✅ |
| 6 服务握手进入可用 | PC 侧收到 `initialize` 打 `SESSION`；桌面四层齐了才 `connected` | ✅ 桌面 / ◐ 手机 |

其他要求：无需配置 IP/端口 ✅；一次性 + 时效 ✅；拒绝/超时/重复扫码有中文原因 ✅（`gate.rs` 错误码 + `welcome.reason`）；持久信任 ✅（服务端名单）；**配对授权 ≠ 全部远程控制 ✗**。

### 3.2 日常自动连接

| 要求 | 现状 | 结论 |
| --- | --- | --- |
| 打开即自动连接 | 桌面正式版按开关自动起传输；手机 `keepRemoteAlive` 常驻 | ✅ |
| Wi-Fi/移动网络切换恢复 | Iroh 地址变化 + 退避重连；无系统网络回调 | ◐ |
| 电脑休眠唤醒 / Core 重启恢复 | 桌面探测 + 端口对账 + 桥重建；手机重连依赖票据 | ◐ |
| 短暂断线不打断、不频繁弹窗 | 全局横幅 20 秒阈值；`remoteReconnect.ts` 纯函数 | ✅ |
| 无法恢复时明确离线/服务不可用 | 桌面 `degraded/core_unavailable`；手机没有 `view`，`recover()` 用尽后停在 `connecting` | ◐ |
| 远程总开关，关闭后不擅自恢复 | 桌面 `p2p-prefs.json`；**手机没有对应总开关**，只有切本机/清票据 | ◐ |
| 状态基于真实业务可用性 | 桌面四层；手机只看隧道 | ◐ |

另：手机端没有持久化 `sunday1:` 地址票。`p2p_connect` 只返回 `peer/name`，`remoteSession.ts` 只有结果含 `resume` 才保存；手机实际存的是扫到的 `sunday2:`（5 分钟）。因此“下次自动连接”在应用重启/切设备超过 5 分钟后失效，必须重扫。这与 PRD 3.2 直接冲突。

### 3.3 连接状态

| 状态 | 现状 | 结论 |
| --- | --- | --- |
| 等待授权 | 没有该状态 | ✗ |
| 正在连接 | `connecting` / `dialing` / `PHASE connecting` | ✅ |
| 已连接 | 桌面四层齐了才 `connected`；手机 `connected && !connecting` | ◐ |
| 正在恢复 | 桌面 `degraded` + 20 秒横幅；手机 `lost` 后自动 recover | ✅ 桌面 / ◐ 手机 |
| 离线 | 桌面 `offline`；手机 `disconnected` | ✅ |
| 权限受限 | 没有能力权限层，故没有该状态 | ✗ |
| 四层分别检查 | `state.rs::Layers` + `p2p_host::derive_view`；手机不检查 Core/会话 | ◐ |
| 业务握手 + 基本收发后才算已连接 | 桌面 `initialize` + `/api/health`；手机没有 PC Core 探测或 ping 验证 | ◐ |

## 四、核心能力（PRD §4）

### 4.1 智能连接与自动选路

- Iroh、局域网直连、跨网打洞、中继回退：✅。
- 已建立连接后的路径优化：Iroh 自己会迁移路径，`watch_path` 只负责报告，应用层没有主动优化策略：◐。
- 中继不可用报告实际故障：连接错误会冒到 UI，但没有独立的中继健康状态：◐。
- 连接详情：直连/中继 ✅；**往返延迟、传输速率 ✗**；错误原因 ◐。
- 不要求用户部署服务器 ✅；不承诺所有 NAT 纯 P2P ✅（文档口径正确）。

### 4.2 可信设备与权限

- 设备身份、命名、配对、解绑、即时撤权：✅。
- 密钥安全保存与轮换：私钥普通文件，无轮换：◐。
- 设备认证与操作权限分离：**未分离**；已配对即拥有 Core 全部能力：✗。
- 审计远程访问/授权/拒绝：**没有审计记录**：✗。
- 能力表（查看状态/发消息/文件读取/Agent 任务/屏幕/键鼠/系统命令）：**没有按能力授权**：✗。

### 4.3 可靠消息

- 复用现有协议：✅。
- 唯一 ID：turn/queue 有 `client_message_id`；隧道 `call.id` 只在本连接内唯一；没有通用 `message_id`：◐。
- 状态区分：`Outbox` 有 unknown/pending/accepted/failed，但只在 CLI watch 使用；UI 有 acceptance/uncertain，未持久化：◐。
- 超时 ≠ 失败：`CoreAppServer` 的 `CoreRequestAcceptanceUnknownError` + 同键 5 秒对账：✅。
- 断线恢复未确认消息/任务：UI 内存里有 `uncertainResumes`，重启即丢；`watch` 的 Outbox 未接进手机宿主：◐。
- 会话内顺序：journal `seq` + `thread/resume`：✅。
- TTL / 取消 / 去重 / 重试：取消 ✅（turn.cancel、file cancel）；去重 ✅（turn/queue）；TTL ✗；重试 ◐。
- 副作用不重复：`client_message_id` 覆盖 turn/queue ✅；但 `remoteCodec.ts` 把 `config.`、`settings.`、`workspace/` 前缀都当可重放，而 `config.provider.create`、`config.model.*`、`settings.update` 是写操作，半断线重试可能重复：⚠。
- 过期/撤权指令不在恢复后生效：没有持久指令队列；撤权会拒绝新调用 ✅，但“已入队未执行”的语义没有：◐。
- 传输回执与任务完成回执分开：`turn/accepted` 与任务完成事件已分开 ✅；没有通用投递回执：◐。

### 4.4 文件与数据传输

- 双向传输：**只有拨号方发、服务端收**；手机既没有 `p2p_send_file`，也没有接收循环；桌面→手机需要 `ask` 帧：✗。
- 小文件直接发：✅（引擎已有）。
- 大文件分块：✅ 256 KiB；暂停 ✗；续传 ✗；完整性校验 ✗（只校验字节数）。
- 进度/剩余/失败原因：进度与失败原因 ✅；剩余可由 total - transferred 推导 ✅。
- 移动网络/带宽限制：✗。
- 完成后打开 Easy File / Library：预览与定位 ✅；资料库登记由界面调既有 library 动作 ◐。
- 不强制上传中转：✅（中继只转发加密流量）。
- 未授权路径不可读：**没有路径级授权**；已配对设备可调 Core 的文件接口：✗。

### 4.5 任务与会话接力

- 手机查看电脑任务、发起桌面任务、收审批：✅（同一 Core 会话经隧道）。
- 任务完成通知：只有应用内事件；`capabilities.notifications=false`，没有系统通知：◐。
- 内容/文件引用移交：✗。
- 保留任务身份/授权/进度/结果/上下文：同一 thread 天然保留 ◐；没有跨设备接力元数据：◐。
- 同一任务不重复执行：turn/queue 幂等 ✅；其他写操作 ◐。

### 4.6 Android 后台连接

- 后台保留必要连接：**没有连接前台服务**；`SundayOverlayService` 只服务标注层；应用被系统冻结后连接随进程休眠：✗。
- 重新打开后恢复：`keepRemoteAlive` + `boot` 重连 ✅（但受 5 分钟票据问题影响）。
- 用户选择是否常驻连接服务：✗。
- 避免高频心跳：应用层 5 秒 ping、QUIC 10 秒 keepalive；没有按网络/前台状态自适应：◐。
- 电量/通知/系统限制说明：✗。
- 网络变化/VPN 冲突/后台限制诊断：✗。

## 五、P2 / AI 通讯 / 指标

- **§5 虚拟局域网**：未实现；仓库没有 EasyTier 集成或评估记录。`core/plugins/bundled/network-exploration` 是网络诊断插件，不是虚拟网卡。✗
- **§6 AI 通讯预留**：传输层与界面已分离 ✅；但没有统一通讯对象、消息信封、发送者/接收者/会话/任务/权限/生命周期字段，也没有离线持久队列。◐
- **§7 量化验收**：没有 P50/P95、连接成功率、24 小时资源曲线等采集；只有 `p2p.log` 阶段行。✗

## 六、产品验收场景（PRD §8）

| 场景 | 结论 | 说明 |
| --- | --- | --- |
| A 首次连接 | ◐ | 扫码即可用，但缺少“电脑确认”这一步 |
| B 电脑不在身边 | ✅ | 移动网络经中继可连；受票据过期与手机状态判定影响 |
| C 中途断网 | ◐ | turn/queue 幂等与事件回放有；待确认队列不持久，桥重建补事件不完整 |
| D 大文件断线续传 | ✗ | 无续传、无校验和 |
| E 设备丢失撤权 | ✅ | 撤销即时生效，活跃连接下一次调用即被拒 |
| F 虚拟局域网 | ✗ | 未实现 |

## 七、已通过、不需要重做

- 旧账号/自建 relay 网关已删；`core/desktop/src-tauri/src/remote/` 只剩 `fixtures/`，CLI 无 mobile/remote 子命令。
- 一次性签名配对票、陌生设备拒绝、重复使用拒绝、撤销后旧票不能复活。
- 撤权对活跃连接当场生效（每条调用 + 每秒复核 + 明确错误码 + 关闭前宽限）。
- 结构化状态通道 `SUNDAY-P2P/1`，坏行明确报错，不再靠切空格。
- 桌面四层状态、Core 探测缓存、端口对账、进程守护、启动自启、退出收进程。
- 隧道并发调用、心跳判死、断线置失败、事件泵、RPC 桥重建。
- REST 字节透传（附件/图片/PDF）、chunked 解码、响应头保留。
- 单文件互传的落盘安全（净化、重名、`.part`、权限先拒）。
- `sunday-p2p.exe` 的 CI/打包/安装器强制包含。

## 八、C1 范围建议（按依赖排序）

### S1 手机地址票落地（P0，最小改动）

- `p2p_bridge::p2p_connect` 返回 `resume: client.resume_ticket()`。
- `RemoteConnectionPanel` 用返回值更新 `saveResumeTicket` 与设备清单里的票。
- 验收：配对后等 6 分钟、杀进程重开，仍能用 `sunday1:` 自动连上；设备清单切换不再要求重扫。

### S2 配对确认（P0）

- `gate::Admission` 增加 `Pending`；首次有效票只写“待确认记录”，不进可信名单，连接被拒并带 `pairing_pending`。
- 桌面新增待确认列表与 `p2p_confirm_device` / `p2p_reject_device`；确认后才写 `TrustStore`。
- 手机显示“等待电脑确认”，按退避重试；超时/拒绝给明确原因。
- 验收：扫码后未确认时任何 RPC 被拒且名单无此设备；确认后下一次连接直接可信；拒绝后进入撤销记录。

### S3 手机端真实可用状态（P0）

- 手机宿主在拨号成功后做一次 `initialize` + `ping`，把 `session` 与 `core` 事实纳入 `p2p_status`；返回 `view/reason/layers`。
- UI 用 `view` 而不是裸 `connected`；`recover()` 用尽后落 `disconnected` 并给原因。
- 远程请求补 `timeoutMs`/`AbortSignal`。
- 验收：杀掉 PC Core → 手机显示降级；Core 回来 → 自动回 `connected`；隧道半死时请求不会无限挂起。

### S4 消息可靠性与重放边界（P0）

- 收紧 `isReplaySafe` 为显式只读方法白名单；`config.*` 写、`settings.update`、`workspace/*` 不再自动重放。
- 把 UI 的 `uncertainResumes` 持久化，重开应用先按同一 `client_message_id` 对账再决定重发。
- 给待发指令加 TTL；过期未执行不再补发。
- 验收：断网时发 `config.provider.create` 不产生重复 provider；turn.start 重试不重复执行；过期队列项不再生效。

### S5 事件补齐与审计（P0/P1）

- `CoreRpc::connect_from` 在重建后补一次 `thread/resume`，或让 Core 真正消费 `lastSeenSeq`；桥重建时向界面发 `thread/gap`。
- 桌面写 `p2p-audit.jsonl`：配对待确认/确认/拒绝、连接、撤权、文件传输、远程方法类别。
- 验收：桥断期间产生的审批/后台事件在重连后能补回；审计可按设备/时间查询。

### S6 连接详情与度量（P0）

- `ping` 记录 RTT，`p2p_status` 暴露；传输速率由进度计算；错误原因分类。
- 采集建连/重连耗时，先落日志与状态，再决定是否做统计面板。
- 验收：设备页能看到 direct/relay、RTT、速率、错误码；P50/P95 可从日志汇总。

> 文件双向/续传/校验、能力权限、Android 前台服务、虚拟局域网分别属于 C2/C3，不塞进 C1。

## 九、需要产品决策

1. **配对确认的交互**：建议“拒绝当前连接 + 保留待确认记录 + 手机显示等待”，确认后手机自动重试；不采用“保持半开连接等确认”。
2. **能力权限的粒度**：C1 是否先只拦高风险能力（终端、键鼠、屏幕、工作区外文件），其余按已配对放行；还是 C1 就做完整能力表。前者能更快满足“配对 ≠ 全部控制”。
3. **文件方向**：桌面→手机需要服务端发起调用（`ask` 帧）；手机→桌面需要手机宿主接 `send`/接收循环。建议先做“手机→桌面发送”（复用现有 `send`），再做桌面→手机。

## 十、未验证与风险

- 未做真机：Android 前后台、休眠、Wi-Fi/蜂窝切换、扫码方向、通知权限。
- 未做干净 Windows 安装包实跑；未做 24 小时资源曲线；未做受限 NAT/第三方 VPN 场景。
- 桌面 Core 默认无令牌：本机任意进程可绕过隧道直接调 Core；这是安全模型的已知缺口，不是 C1 能顺手解决的，需要单独决定。
- `core/remote/relay` 与 `core/mobile` 是旧栈残留，容易和当前 Iroh 中继概念混淆；建议归档或删除，但会动历史文档引用。

## 附：本机测试证据

```text
cargo test --manifest-path core/p2p/Cargo.toml --lib
  test result: ok. 70 passed; 0 failed

cargo test --manifest-path core/p2p-status/Cargo.toml
  test result: ok. 5 passed; 0 failed

cargo test --manifest-path core/desktop/src-tauri/Cargo.toml --bin Sunday p2p_host
  test result: ok. 15 passed; 0 failed

cargo test --manifest-path core/p2p/Cargo.toml --test transfer_two_processes
  test result: ok. 2 passed; 0 failed

npx vitest run tests/remote-reconnect.test.ts tests/remote-codec.test.ts \
  tests/remote-panel-layers.test.ts tests/remote-reconnect-banner.test.ts
  Test Files 4 passed; Tests 18 passed
```

关键证据文件：`core/p2p/src/{pair,gate,trust,link,rpc,events,proxy,transfer,state,watch,recovery}.rs`、`core/p2p-status/src/lib.rs`、`core/desktop/src-tauri/src/p2p_host.rs`、`core/android-host/src-tauri/src/{p2p_bridge,runtime,lib}.rs`、`core/ui/src/{transport/remoteTransport.ts,transport/remoteCodec.ts,app/remoteSession.ts,app/remoteReconnect.ts,components/RemoteConnectionPanel.vue}`、`core/src/lamtools_core/app/{live_router.py,live/threads.py,api_access.py}`、`agent_docs/p2p-remote.md`、`scripts/verify-p2p-p0.ps1`、`scripts/verify-p2p-p1.ps1`、`scripts/verify-p2p-p2.ps1`。
