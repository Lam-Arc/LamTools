# 设备间连接（P2P 传输层）

`core/p2p` 是独立 crate，Windows 与 Android 共用同一份实现。它只做四件事：身份、
配对票据、可信设备、把一帧 JSON 送到对面并拿回一帧。会话、工具、审批都不在这一层，
它不知道自己搬的是业务。

## 为什么用 Iroh

Iroh 直接给到 QUIC 流、节点公钥身份、打洞和中继回退，不用自己拼 STUN/TURN。
`presets::N0` 带 n0 的公共 relay 与 DNS 发现：默认零配置可用，relay 只转发加密流量，
直连成功后 relay 就退场。要换自己的 relay 只改 `identity.rs` 里构造 endpoint 的参数。

Android 注意：iroh 的默认 DNS 解析器要读系统 DNS，需要先装 JNI 上下文
（`iroh::dns::install_android_jni_context`），否则会走回退域名服务器。接 Android 宿主
时必须先做这一步。

## 协议

一个 ALPN：`sunday/p2p/1`。连上后拨号方开一条双向流，先发 `hello`，被叫方回
`welcome`（带自己的节点 id 和是否已信任）。之后就是帧：

```
u32 大端长度 + UTF-8 JSON
{ "kind": "call",  "id": 7, "method": "…", "params": {…} }
{ "kind": "reply", "id": 7, "result": {…} }
{ "kind": "error", "id": 7, "message": "…" }
{ "kind": "event", "method": "…", "params": {…} }
```

`method` 与 `params` 就是 Core 本来在说的那套 JSON-RPC，到了对面直接交给同一个
Python Core，不新增业务实现。

## 配对与信任

两种票据，一种用途：

- `sunday2:` —— **一次性配对票**（扫码用）。`base64url({"b": 正文, "s": 签名})`，正文是
  节点 id、地址、过期时间、一次性随机数；签名用出票方节点私钥，校验用票据里同一个节点
  公钥。**有效期 5 分钟上限，用过即作废**，记录落在出票方的 `p2p-pairing.json`（进程重启
  也记得）。手动重新生成会作废当前码。换网或中继地址变动会自动出新码，已经登记的配对申请
  可以在原有效期内继续等待确认。
- `sunday1:` —— **地址票**（已配对设备重连用）。只有节点 id 与地址，不代表授权；授权由
  可信名单判定。`sunday-p2p call` 在配对成功后会打印 `RESUME sunday1:…`，手机存它即可
  下次重连，不需要再扫。

握手时拨号方把自己的票放在 `hello.pair` 里（重连不带）。服务端判定顺序：

1. 撤销记录优先。被移除的设备带旧码回来一律拒绝；想回来必须重新生成一张新码再扫。
2. 名单里的设备直接放行（重连静默）。
3. 陌生设备必须带一张有效的一次性票，伪造/过期/用过都会被拒，原因写进 `welcome.reason`，
   手机端原样显示（「这张配对二维码已经用过了，请在电脑上重新生成一张」）。

**没有「首次连接即信任」这条路了**：不知道是谁的设备连不进来。

撤销是即时的：每条远程调用前都会按文件时间戳重读 `p2p-trust.json`（没变就只 stat 一次），
另外每秒复核一次，所以已经建立的连接也会当场失去权限——返回 `Frame::Error`，
`code = device_revoked`，然后断开。不会出现「列表里已经没有它，它还能调 Core」。

票据不进日志：`p2p.log` 默认只记前缀（`SUNDAY_P2P_LOG_TICKET=1` 才记全文）。

## 已验证（Windows，本机两进程）

```
$ sunday-p2p serve --dir …/p2p-pc --name PC
TICKET sunday1:eyJpZCI6IjNlZmI4NzU2…
READY
PEER 3efb8756…                 # 第一次连接，写入可信名单
$ sunday-p2p call … --ticket … --method whoami
RESULT {"device":"PC"}
$ sunday-p2p call … --method echo --params '{"hello":"sunday"}'
RESULT {"hello":"sunday"}
```

可信名单落盘后第二次连接不再询问。这次走的是局域网地址直连，没有经过 relay。

## 落地形态（2026-11-05）

桌面端把传输跑在**独立进程** `sunday-p2p` 里，而不是链进桌面应用。原因不是设计偏好，是依赖：
iroh 的 `netwatch` 在 Windows 拉 `wmi`，与桌面端已有的 windows crate 版本冲突，硬合并会让
桌面构建直接坏掉（16 个 E0277/E0308/E0599）。独立进程本来就是这套东西的定位，桌面宿主只
负责起停与转述。

因此也关掉了 iroh 的 `portmapper`（它同样带 wmi）。代价是少了 UPnP/NAT-PMP 端口映射；
直连、打洞与中继回退都不依赖它，关掉后本机两进程实测仍通。

- 桌面：`p2p_host.rs` 起 `sunday-p2p serve --core-port <get_api_base 的端口> --core-token <env>`，
  读它的 `TICKET` / `EXPIRES` / `READY`，把票据与有效期交给 UI；停止就是杀掉这个进程。
  **正式版启动即自动拉起**（`p2p_host::autostart`，开发版不自动起，可用
  `SUNDAY_P2P_AUTOSTART=1` 强制）。`p2p_status` 返回 `running / error / binary /
  binaryError / expiresAt`，设备页直接显示「运行中 / 未运行 / 失败原因」和二维码倒计时。
- 手机：宿主内直接链接 `sunday-p2p`，命令是 `p2p_ticket / p2p_connect / p2p_call / p2p_status /
  p2p_disconnect / p2p_devices / p2p_revoke`。
- 桌面命令：`p2p_ticket / p2p_serve_start / p2p_serve_stop / p2p_status / p2p_devices / p2p_revoke`。
- UI：`RemoteConnectionPanel`，桌面出票据与接受连接，手机粘贴票据连接；两边都能看/撤销可信设备。

传输程序的位置：`SUNDAY_P2P_BIN` 优先，其次应用同目录，最后开发目录
`core/p2p/target/{release,debug}`。打包版需要把 `sunday-p2p.exe` 放进应用旁边。

开发期要注意两件事：

- 传输程序必须重编过。`core/p2p` 早期产出的二进制只有 `serve` / `call`，没有 `qr`，
  桌面调 `qr` 会把 USAGE 文本当 SVG 显示成一段字。帮助文本现在列出全部四个子命令。
- 单实例锁只在正式（release）构建注册。锁键是 bundle identifier，和已安装的正式版相同；
  正式版在跑时，debug 构建会在插件 setup 里被直接杀掉（进程退出码 0，窗口永不出现）。
  开发实例与正式版并存是正常用法，所以 debug 构建跳过这个锁。

## 事件通道（已打通）

远端只发得出去、收不到回复是不成立的，所以隧道现在是双向的：

- 客户端读帧一直在跑：应答按 `id` 交给对应调用，事件交给订阅者；流断了会把所有等待中的
  调用一次性置为失败，不会挂住。
- PC 侧每接受一台设备就起一条泵：连本机 Core 的 WebSocket（`/app-server`，带同一个
  bearer 令牌），照界面同样的方式发 `initialize`，之后把每条带 `method` 的通知包成事件帧
  推过隧道。断线会重连。
- 手机宿主把事件抛成 `p2p-event`，界面的 `RemoteTransport` 再还原成与本地 IPC 完全同形状
  的 notification。

实测（假 Core 推送一条通知）：

```
$ sunday-p2p call … --method ping --watch 6
PEER 81d9e03138787fc6…
RESULT {"pong":true}
EVENT thread/event {"note":"hello from core","seq":1}
```

## 模式切换

手机启动时看宿主状态：连着电脑就整条走 `RemoteTransport`，否则用本机 Core 的 IPC。
连接或断开之后界面重载一次，通道随之切换。本机 Core 一直活着，重开仍是同一个会话。

## 二维码与自定义中继（已接）

- 二维码由 `core/p2p/src/qr.rs` 生成 SVG（`qrcode` crate），两端共用；桌面「远程连接」页
  出码，票据文本就在旁边，扫码和粘贴是同一张票据。宿主命令 `p2p_qr(ticket)`。
- 自定义中继：`SUNDAY_P2P_RELAY` 或 `SUNDAY_P2P_RELAYS`（逗号分隔）配了就改用
  `RelayMode::custom`，只用你配的节点；不配就用 `presets::N0` 的公共 relay（仅回退）。
  地址支持 HTTP 或 HTTPS。配置全部无效时，桌面显示配置错误。中继只按节点 id 转发加密流量。

## 旧网关已删除

`core/desktop/src-tauri/src/remote/`（gateway / pairing / relay / tunnel / account，
约 5.8k 行）连同 `main.rs` 里的 9 个 `remote_*` 命令、控制端口、`__LAMTOOLS_REMOTE_*`
桥接、`sunday mobile` 这组 CLI 一起删掉了。账号与自建 relay 那条路不再存在。
桌面 `cargo check` 与桌面前端构建都通过。

## 扫码（已接）

手机端「远程连接」页有「扫码」：调系统相机拍一张，`core/p2p/src/scan.rs` 用 `rqrr` 解码，
拿到的就是桌面那张票据，直接填进输入框。解码与编码在同一个 crate，格式只有一份。
单元测试做了真实的往返：`qrcode` 画出 PNG，`rqrr` 读回来，字符串逐字节相等。

## 打包（2026-11-17）

`sunday-p2p.exe` 现在是正式安装包的一部分：

- `.github/workflows/release.yml`：「Build P2P transport binary」（
  `cargo build --release --manifest-path core/p2p/Cargo.toml`）+ 校验帮助文本列齐
  `serve/call/qr/scan/devices/revoke`；staging 时复制到 `Sunday.exe` 同级。
- `scripts/package.ps1`：本地打包走同一条命令、同一处复制。
- `core/desktop/installer/Sunday.iss`：显式 `Source` 一行；`build-installer.ps1` 把
  `sunday-p2p.exe` 列进必需文件，缺了直接打包失败（不发「远程连接默默不可用」的安装包）。

## 验收脚本

`scripts/verify-p2p-p0.ps1` 用真实两进程跑一遍 P0：

- 出票是 `sunday2:` 且有效期 ≤ 5 分钟；
- 一张码扫一次即配对，第二次换设备重放被拒；
- 没有票的陌生设备被拒且不进名单；
- 已配对设备用 `RESUME sunday1:` 重连，不需要重新扫码；
- 已建立的连接在 `revoke` 之后的下一次真实调用拿到 `device_revoked`。

## P1：自动恢复与真实状态（已完成）

五项都在同一套判定上收口，桌面、传输进程、界面各用一份、说同一句话。

- **自动连接**：`p2p_host::autostart` 在正式版启动、Core 就绪后自动拉起传输；开关落在
  `%APPDATA%/Sunday/p2p/p2p-prefs.json`（`p2p_ticket` 置真、`p2p_serve_stop` 置假），
  设备页有对应开关（`p2p_config_get/set`）。已配对设备重连用 `RESUME sunday1:` 地址票，
  不需要重新扫码。
- **消除假在线**：`core/p2p/src/state.rs` 把状态拆成 传输 / 设备 / Core / 会话 四层，
  `Layers::usable()` 四层齐了才成立；桌面 `p2p_host::derive_view` 是同一判定的宿主版
  （纯函数，带单测）。界面只认 `view`：`degraded` 必须显示一句原因，`connecting` 不算连上。
- **会话已恢复有证据**：传输进程真的收到 `initialize` 时打印 `SESSION <peer>`，宿主
  解析这一行才把 session 层置为 resumed；断开 / 新连接立刻回落，不再用「有设备 + Core 通」猜。
- **自动恢复**：`watch`（参考实现）与宿主 `supervise` 都按退避重连；Core 换端口时
  `p2p_status` 对账并重启传输进程；界面 `thread/resume` 带 `last_seen_seq` 按游标补齐，
  隧道侧另发 `thread/gap` 让界面自己续订，不盲拉全量。
- **消息可靠性**：`recovery::Outbox` 定义四种送达状态，只有收到回执才算已发送；同一
  `client_message_id` 复用（Core 侧按它去重），断线后先查状态再决定是否重发。
- **等待体验**：宿主在阶段变化时广播 `p2p-progress`（waiting / connecting / connected /
  degraded），界面据此当场换文案，不必等 3 秒轮询；`degraded` 同时给出原因。
- **验收**：`scripts/verify-p2p-p1.ps1` 用真实两进程跑「四层齐了才 connected / Core 挂了
  降级 / Core 回来重新 initialize / 隧道断了自动重连 / 长断线才提示」。

## P1 遗留收口（2026-11-17）

五条都是「会静默出错」的点。每条按「现状 → 改了什么 → 怎么证明」写。

### 1. 事件泵重连不带游标 → 游标放进泵

- 现状：`pump_core_events` 每次 `initialize` 都不带 `lastSeenSeq`；断线那几秒的 journal
  事件只能靠界面自己 `thread/resume` 兜底，不走 store 续订的页面（审批、后台任务、桌宠）
  会静默少事件。
- 改了什么：`core/p2p/src/events.rs` 新增 `Cursor`（记 `seq` 与所属会话，只前进不后退）、
  `pump_core_events_with_cursor`（重连时 `initialize` 带 `lastSeenSeq`，并对已知会话补一次
  `thread/resume`）、`pump_until_closed_from`；`rpc::CoreRpc::connect_from(port, token,
  last_seen_seq, thread)` 让 RPC 桥重建也带上位点；`bin/cli.rs` 的事件腿每转发一条就记位点，
  桥重建时用它（日志 `RPC-CHANNEL REBUILT last_seen_seq=`）。
- 怎么证明：`cargo test --manifest-path core/p2p/Cargo.toml --lib` 里 4 条单测（位点来自
  事件本身 / 只进不退 / 流式增量 `seq=0` 不算位点 / 握手参数只在真的见过事件时才带）。
  桥重建带位点的端到端（需要 Core 真的重启）见「真机待验」。

### 2. `recovery::Outbox` 只是库 → 接上宿主消费

- 现状：账本能记「未知」，但没有任何入口把「查到的事实」写回去；重发路径要么不敢发、
  要么当成新写。
- 改了什么：`Outbox::settle(key, found)`（有→算送达、没有→允许同键重发、查不到→维持未知）
  与 `Outbox::restore(key)`（进程被杀在「已发出、未收到回执」时的恢复）；
  `watch::ReliableSend` 是宿主侧的消费者：`send` 用幂等键登记、断线时把在途标成未知、
  `reconcile` 在重发前按会话查日志（`thread/resume` + 幂等键在返回里出现与否）、
  `restore_pending` 恢复重启前的悬空写。CLI `watch` 暴露 `--thread / --send-key /
  --send-method / --send-params / --restore-pending`，打印 `SEND key=... decision=new|duplicate
  state=...` 与 `RECONCILE key=... verdict=accepted|resend|unknown`。
- 怎么证明：`cargo test --lib` 里 4 条（结算三种结论 / 恢复出来的写进待查清单 / 显示状态只有
  回执后才是 sent / 断线把在途变未知）；`scripts/verify-p2p-p2.ps1` 用真实两进程断言
  「恢复出来的写先去查（`RECONCILE`）而不是盲目重发」「同键重连是 `decision=duplicate`，
  不是第二次写」。

### 3. `SESSION` 靠 stdout 文本 → 结构化状态通道

- 现状：宿主切空格读 `SESSION <id>` / `PEER <id> trusted=...`；加字段就改下标，改错一位
  界面就一直显示「没连上」。
- 改了什么：新增瘦 crate `core/p2p-status`（只依赖 serde）：`PREFIX = "SUNDAY-P2P/1 "`、
  `StatusEvent`（ticket / relay / peer / peer_closed / session / path / core）、
  `render()` 与 `parse_line()`。三条规矩：带前缀的行是契约；前缀对但内容坏 → `StatusError`
  （必须报出来）；没有前缀 → 不是状态行（不是错误）。传输进程两种行都打（兼容老脚本），
  宿主只认结构化行，坏了把原因写进 `p2p_status.protocolError`，设备页直接显示。
- 怎么证明：`cargo test --manifest-path core/p2p-status/Cargo.toml`（5 条：全事件往返 /
  坏行报 Malformed / 版本不认识报 UnknownVersion / 旧文本不是状态行 / 缺 event 名要报错）；
  `scripts/verify-p2p-p2.ps1` 把传输进程日志里**每一行** `SUNDAY-P2P/1` 都用
  `ConvertFrom-Json` 校验并要求有 `event` 字段——坏一行整个脚本失败。

### 4. `p2p_status` 每次全量探测 Core → 1.5 秒 TTL

- 现状：一次探测最长 800ms 连接 + 1200ms 读；界面一秒问几次就是几次真实 TCP 连接。
- 改了什么：`p2p_host::ProbeCache`（默认 1.5s）：端口不同或超过 TTL 就重新真探；Core 换端口
  时 `invalidate()`；`p2p_status`（异步，走 `spawn_blocking`）与宿主推送线程共用同一份缓存。
- 怎么证明：`cargo test --bin Sunday p2p_host` 里
  `the_core_probe_is_cached_only_for_a_moment`（TTL 内复用 / 超时重探 / 换端口不冒充 /
  invalidate 生效）。

### 5. 验收脚本只断言 CLI 的 NOTICE → 补 UI 侧步骤

- 改了什么：`core/ui/src/app/remoteReconnect.ts` 新增纯函数 `outageBanner({elapsedMs, status})`
  （连着不弹、20 秒内不弹、超过阈值才弹并给一句话）；`scripts/verify-p2p-p1.ps1` 新增第 6 段，
  跑 `core/ui/tests/remote-reconnect-banner.test.ts`。
- 怎么证明：该测试 5 条（连着不弹 / 19.999s 不弹 / 20s 弹 / 降级同阈值 / 无状态时说「断了，
  仍在重连」）；P1 脚本第 6 段断言它退出码为 0。

## P2（2026-11-17）

### 6. 真实路径显示（直连 / 中继）

- 现状：界面只能说「连上了」，打洞成功和整条流量走中继看起来一样。
- 改了什么：`core/p2p/src/link.rs` 新增 `PathKind`（direct / relay / unknown）与判定
  `classify_path`（**只认当前选中的那条路径**；还没选中时才按可用路径给倾向），
  `Client::path()` / `ServerLink::path()` 读实时快照，`watch_path()` 用 iroh 的
  `path_events()` 事件流报变化（没有变化就没有唤醒）。传输进程打印 `PEER ... path=`
  与 `PATH <peer> path=`（旧格式 + 结构化各一份）；宿主 `p2p_status.path` 给当前设备、
  `devices[].path` 给每台；设备页把「连接方式」收进可展开的「连接详情」，不占主界面。
- 怎么证明：`cargo test --lib` 里 4 条（选中优先于候选 / 未选中按可用路径 / 全无 → unknown /
  标签往返）；`scripts/verify-p2p-p2.ps1` 在本机两进程上断言服务端与客户端都打出
  `path=(direct|relay|unknown)`（本机实测为 `direct`）。

### 7. 设备切换（多设备，当前连接随之更新）

- 现状：宿主只有一个「当前手机」的 `Option<String>`；第二台连上来界面还是第一台，切换后
  会话/路径还挂在旧设备上。
- 改了什么：`p2p_host::DeviceBook`（`peers` + `current`）：新连接不抢当前（没人用时才成为
  当前）、当前断开退到最近上线的一台、切换不存在的设备当场失败；`p2p_status` 的
  `peer / deviceName / path / layers.session` 全部只从**当前那台**取，另给 `devices[]`
  （带 `current` 标记）；新命令 `p2p_switch_device`；设备页在有多台在线时列出并切换。
- 怎么证明：`cargo test --bin Sunday p2p_host` 里 4 条（切换后各层跟着换 / 关掉当前回落到
  在线的一台 / 重连不带「会话已恢复」/ 被拒绝的连接不进名册）；`peer_name` 来自握手，
  设备清单显示名字而不是节点 id（`PEER` 行与结构化 `peer` 事件都带）。

### 8. 轮询收敛到事件驱动

- 现状：设备页每 3 秒调一次 `p2p_status`，页面开着就一直唤醒；`p2p_status` 每次还要探 Core。
- 改了什么：宿主 `p2p_host::start_emitter` 每 2 秒算一次快照，**只有真的变了才 `emit
  ("p2p-state")`**，且没有设备在线时完全不探 Core（有设备时走 1.5s TTL 缓存）；
  界面删掉 3 秒轮询，改为收 `p2p-state` + 窗口重新可见/获得焦点时对齐一次，
  二维码倒计时只在有码时走、页面不可见就停。
- 怎么测前后差异（同一台机器、设备页停留 5 分钟、无手机连接，改前用旧构建、改后新构建）：

  ```powershell
  # CPU 秒：两次采样之差（同一次运行里不要开别的重活）
  $p = Get-Process Sunday -ErrorAction SilentlyContinue
  $a = $p.CPU; Start-Sleep 60; $p.Refresh()
  "CPU seconds in 60s: " + [math]::Round($p.CPU - $a, 3)

  # 定时器与唤醒：能量报告里看 Timer Resolution / 平台定时器请求
  powercfg /energy /duration 60 /output $env:TEMP\sunday-energy.html
  # 打开报告，看 "Timer Resolution Requests" 与进程相关的定时器条目数量
  ```

  改前：设备页停留期间每 3 秒一次 IPC + 每秒一次探测（3 秒节拍里还夹着重新生成二维码的
  风险）；改后：没有状态变化时 60 秒内的 CPU 增量应接近 0，且能量报告里的定时器请求不随
  页面停留时间线性增长。

### 9. Android 前后台恢复：桌面侧已就绪，手机侧怎么接

本仓库只有桌面端；手机宿主不在仓库里，所以这里是**桌面侧准备好的状态与接口**，以及手机侧
必须照着做的步骤。桌面侧：

- `p2p_resume_state` 一次返回 `sunday.p2p.resume.v1` 快照：`transport`（running / port /
  ticket / expiresAt / expiresIn / autoConnect）、`current`（id / name / path / session）、
  `devices[]`、以及 `reconcile.requires = "thread/resume"` 的契约说明。
- 传输进程侧的不变式（手机回来后一定成立）：可信设备重连**不需要重新扫码**（`sunday1:`
  地址票 + 信任名单）；重连的 `initialize` 可以带 `lastSeenSeq`；`PATH` 会告诉你这次走直连
  还是中继；`SESSION <peer>` 只有真的 `initialize` 过才出现。

手机侧恢复流程（按顺序，每一步都有对应的桌面侧保障）：

1. 回到前台先看本地保存的 `sunday1:` 地址票；没有就提示重新扫码（配对票 5 分钟、一次性）。
2. 用地址票重新拨号（不必重新配对）；被撤销的设备会拿到 `[device_revoked]` 明确错误码。
3. `initialize`（带上次的 `lastSeenSeq`，如果知道）。
4. `thread/resume`（`{thread_id, last_seen_seq}`）把断线期间的 journal 补回来——这是**唯一**
   可靠的补事件方式；补完再刷新界面。
5. 把「已发出、未收到回执」的写恢复进账本（`ReliableSend::restore_pending`），先按幂等键
   查日志再决定重发；查不出来就维持「未确认送达」，不要显示已发送。
6. 只要传输进程还在，桌面的 `expiresIn` 就还有效；为 0 说明需要重新生成二维码。

## 还没做


1. 手机真机整链验收：手机连电脑、看会话、发消息、收审批。电脑这一半已在 2026-11-06
   的 dev 实例里点过——「生成票据」给出票据与真 SVG 二维码；缺的是手机相机扫码那一步
   （本阶段补齐了握手侧的配对与撤权，手机宿主仍需按新的 `hello.pair` 字段传票）。

## 设备文件互传（第二批，最小闭环）

一个文件从 A 到 B：分块、有进度、可取消、失败说得清原因、只允许已信任设备、重名不覆盖。
代码在 `core/p2p/src/transfer.rs`（协议与两端引擎）、`core/p2p/src/bin/cli.rs`（`serve` 收 /
`send` 发）、`core/p2p-status/src/lib.rs`（新增两条状态事件）、
`core/desktop/src-tauri/src/p2p_host.rs`（名册与快照）。

### 协议：只加 method，帧格式一个字节都没改

`call` / `reply` / `error` / `event` 四类帧原样用。互传是四个新 method：

| method | params | 结果 |
| --- | --- | --- |
| `file/offer` | `{id, name, size, chunk?}` | `{id, name, size, chunk, received}`（`name` 是**落盘的真实名字**） |
| `file/chunk` | `{id, seq, data(base64)}` | `{id, received, next}` |
| `file/complete` | `{id}` | `{id, name, path, size}` |
| `file/cancel` | `{id, reason}` | `{id, cancelled}` |

规矩：

- 一次只传一个文件；`seq` 必须从 0 连着来，乱序直接拒（宁可失败，也不写出一个坏文件）。
- 块是 256 KiB（`CHUNK_BYTES`），单文件上限 8 GiB（`MAX_FILE_BYTES`）。
- 收到的数据先写 `.<id>.part`，`file/complete` 时才顶替最终名字；中途取消/超时把 `.part`
  与占位文件一起删掉，不留半个文件。
- 为什么分块走 `call` 而不新开一条 QUIC 流：现有 `call` 已经带「按 id 配对应答」「断链把在途
  调用一次性置失败」「每条调用前复核撤权」，新流要把 `ServerLink::serve` 的读循环重写一遍。

### 错误码（稳定词，界面按它分支）

| 码 | 含义 |
| --- | --- |
| `file_untrusted` | 未配对或已被移除授权（**拒绝发生在写盘之前**，目录里不会多任何东西） |
| `file_bad_name` | 名字是空、`..`、或 Windows 保留设备名（`CON`/`NUL`/`COM1`…） |
| `file_bad_request` | 参数缺失、块序号不对、块超过 256 KiB |
| `file_too_large` | 超过单文件上限 |
| `file_not_found` | 这个 id 不在进行中（过期、取消过、没 offer） |
| `file_busy` | 同时传的太多（上限 8），或同名文件堆到 999 份 |
| `file_disk_error` | 写盘失败（磁盘满、目录不可写、重命名失败） |
| `file_size_mismatch` | 收到的字节数与声明不一致 |
| `file_timeout` | 180 秒没有新块（传输作废，文件清掉） |
| `file_cancelled` | 对端取消或本端取消 |
| `file_peer_error` | 对端拒了这一次调用（消息里带对端的码与原因） |

错误帧的 `message` 形如 `[file_bad_name] 文件名是空的`：码在内、原因在外，脚本取码、人读原因。

### 进度事件（走既有 `event` 帧，不新开通道）

`event` 的 method 是 `file/progress`，params 与 `transfer::Progress` 同形：

```json
{"transfer_id":"6afca0aa-1","direction":"receive","name":"payload.bin",
 "total":716800,"transferred":716800,"percent":100,
 "state":"completed","path":"C:/.../received/2026-11-17/payload.bin"}
```

- `direction`：`send` / `receive`（本端视角）。
- `state`：`offered` → `transferring` → `completed` / `failed` / `cancelled`。
- `code` / `message` 只在失败或取消时出现；`path` 只在完成时出现。空字段不序列化，界面
  不会被空串覆盖掉上一次的真实值。
- 发送端每 1% 发一条，接收端百分比变化时发一条：1 GB 文件约 100 条，不占隧道。

### 落盘与登记规则

- 目录：`<receive_root>/<YYYY-MM-DD>/`（UTC 日期，不依赖本地时区）。`receive_root` 由
  `serve --receive <dir>` 指定；桌面宿主固定用 `<lam_home>/received`（`<lam_home>` 即
  `%APPDATA%/Sunday`，传输进程自己的数据目录是它下面的 `p2p`）。
- 文件名净化：只取最后一段（`../../etc/passwd` → `passwd`，`C:\x\y.txt` → `y.txt`），去掉
  控制字符与 `<>:"|?*`，去掉结尾的点与空格，拒绝空名/`..`/保留设备名，超长（>120 字符）
  截断但保留扩展名。
- 重名不覆盖：用 `create_new` 抢名字，撞车自动 `a.txt` → `a (2).txt` → `a (3).txt`；
  `file/offer` 的应答里回的就是这个真实名字（两端看到同一个名字）。
- 落盘事实走状态通道的 `received` 事件（带绝对路径、大小、来源设备），宿主收进名册
  （`p2p_status` / `p2p-state` 的 `received[]`），界面据此开预览或所在文件夹、按既有的
  `library` 动作登记资料库。

### 状态通道新增两条（`SUNDAY-P2P/1`）

```
{"event":"transfer","transfer_id":…,"direction":"receive","percent":42,"state":"transferring",…}
{"event":"received","transfer_id":…,"path":"C:/…/received/2026-11-17/a.txt","size":123,"from":"手机"}
```

字段与 `transfer::Progress` 一致；`p2p-status` 的往返测试覆盖了它们，字段名对不上会当场失败。

### 怎么用 / 怎么验

```bash
# 收：桌面这一侧（宿主就是这么起的）
sunday-p2p serve --dir <p2p 数据目录> --name PC --receive <lam_home>/received

# 发：拨号方（手机宿主将来调同一份实现）
sunday-p2p send --dir <客户端数据目录> --ticket <sunday2:…> --file <本地路径> [--as <对端看到的名字>]
```

测试（只跑相关的那几条）：

```bash
cargo test --manifest-path core/p2p/Cargo.toml --lib transfer::          # 12 条：净化/分块/重名/未授权/进度形状
cargo test --manifest-path core/p2p/Cargo.toml --test transfer_two_processes  # 2 条：真实两进程互传 + 无票被拒
cargo test --manifest-path core/p2p-status/Cargo.toml                    # 5 条：含新增的 transfer/received
cargo test --manifest-path core/desktop/src-tauri/Cargo.toml --bin Sunday p2p_host  # 含名册两条
```

实测结论（本机，2026-11-17）：

- 700 KiB 文件跨三块（256K/256K/188K）落盘后与源文件逐字节相等；服务端打出 `offered` 与
  `completed`（`percent=100`）两条 `transfer` 状态行，以及一条带绝对路径的 `received`。
- 同名再发一次落成 `payload (2).bin`，第一份内容未变。
- 使用无效地址票的设备发不出去，`--receive` 目录里一个文件都没有（拒绝发生在写盘之前）。

### 手机侧要做什么（本仓库没有手机宿主）

手机宿主在现有链路（dial 方）上加一件事：`file/*` 走到 `Client::dial` 之后**不要**转给 Core，
交给 `sunday_p2p::transfer::Receiver::new(<应用收到的目录>, trusted, sink)`；进度用
`link::write_event(…, "file/progress", …)` 转发或用宿主自己的 UI 通知。桌面的
`serve` 已经这么做了（`core/p2p/src/bin/cli.rs` 的 `serve`），照着写即可。

### 下一步（本批明确不做）

- **桌面 → 手机**：现在只有「拨号方发、服务端收」。桌面是服务端，它要把文件推给手机，需要
  一条服务端发起的调用（新增帧类型 `ask`：服务端发，客户端用既有 `reply`/`error` 回）。
  服务端读循环要加一张在途 `ask` 表，客户端要能挂一个 ask 处理器；`transfer::send_file`
  只认「一次调用」这个形状，接口已经就位，缺的就是这条帧与两侧的转接。
- **断点续传的跨重启恢复**：需要传输状态落盘（id / 已收字节 / 目标路径 / 对端声明的大小），
  并在 `file/offer` 里加一个 `resume_from` 字段；现在同一个 id 不能续。
- **多文件与目录打包**：现在是「一个文件一次传输」，多选要一层队列（`TransferBook` 已经在
  宿主侧记录多次传输，队列还没做）。
- **资料库自动登记**：目前落盘事实交给界面调用既有 `library` 动作；要让「人不在电脑前也
  登记」，得给 Core 一条「按绝对路径登记」的入口，而不是让 Rust 猜项目。
- **大文件吞吐**：分块目前是顺序往返（一块一个应答）。要更高吞吐可以改成窗口式在途多块，
  协议不用变（`seq` 已经是显式的）。
