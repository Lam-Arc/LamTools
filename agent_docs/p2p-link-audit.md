# 连接、配对、投递链路审查

第一轮：2026-11-08（功能打通后的结构性问题）
第二轮：2026-11-09（全量复审：每条链路逐文件通读，含客户端查表、写盘、重连与事件投递）

> 读日志与源码时注意：命令输出的脱敏层会把 `Bearer {token}\r\nConnection: ...` 这类片段替换成
> `Bearer [REDACTED] ...`。判断字段是否真的存在，要用 `od -c` 或 `grep -c` 交叉验证，不要直接相信
> 被改写过的行。本轮 `proxy.rs` 就因此被误判过一次，核对后源码是正确的。

## 结论摘要

链路功能是通的（真机远程五步、手机本地独立运行都已过），但有三块「用户会直接撞上」的缺口：

1. **远程模式下所有非 JSON 的 HTTP 都不通**：附件上传、图片/PDF 预览、素材库、项目文件上传都会失败，
   因为隧道这一层只搬文本，而界面还在往里塞 multipart 字节。
2. **「撤销设备」是假的**：传输进程把可信名单放在内存里，撤销只改了磁盘文件，那台设备在下一次传输
   进程重启之前仍然能连进来，而且会在下一次写入时被写回文件。
3. **断线只能靠下一次操作发现**：隧道没有心跳，也没有把断线报给界面；空闲时断线，流式输出静默停止，
   设备页还显示「连接正常」。

上一轮已知、本轮仍然存在的问题（请求串行、单设备接受、事件 Lagged 丢帧、busy 分支撒谎）也都在下面
重新编号列出，没有消失。

## 审查范围

| 文件 | 体量 | 结论 |
| --- | --- | --- |
| `core/p2p/src/link.rs` | 380 行 | 帧协议、握手、读写任务。超限帧会关整条隧道；无心跳 |
| `core/p2p/src/rpc.rs` | 230 行 | Core JSON-RPC 桥。死桥可重建；Lagged 丢帧；initialize 缓存正确 |
| `core/p2p/src/events.rs` | 121 行 | 旧事件泵（只在没有 RPC 桥时启用）与可达性探测 |
| `core/p2p/src/identity.rs` | 174 行 | 节点密钥、endpoint、relay 配置。密钥文件权限默认 |
| `core/p2p/src/ticket.rs` | 48 行 | `sunday1:` 票据编解码。无有效期、无用途范围 |
| `core/p2p/src/trust.rs` | 89 行 | 可信名单。只在进程启动时加载一次（撤销失效的根因） |
| `core/p2p/src/qr.rs` / `scan.rs` | 62 / 约 90 行 | 二维码生成与解码，实现正常 |
| `core/p2p/src/proxy.rs` | 86 行 | REST 转发。只支持 JSON；32 MB 上限在读完之后才检查 |
| `core/p2p/src/bin/cli.rs` | 470 行 | 服务端主循环。逐条 await、单设备、Lagged 丢弃、不重载 trust |
| `core/android-host/src-tauri/src/p2p_bridge.rs` | 312 行 | 手机宿主。整段持锁、busy 分支撒谎、connect 预算含等锁 |
| `core/android-host/src-tauri/src/client.rs` | 297 行 | 本机 Core socket。死会话重建已修；缓存握手与 resume 正确 |
| `core/android-host/src-tauri/src/picker.rs` | 250 行 | SAF 桥。路径交换正确，进程被杀后请求会悬空到超时 |
| `core/desktop/src-tauri/src/p2p_host.rs` | 358 行 | PC 宿主。无守护、同步命令阻塞、撤销只改文件 |
| `core/ui/src/transport/remoteTransport.ts` | 140 行 | 远程通道。只支持 JSON、不报断线、失败后重放 |
| `core/ui/src/app/remoteSession.ts` | 171 行 | 票据/设备清单。单飞拨号正确 |
| `core/ui/src/core-app/main-android.ts` | 345 行 | 启动、切远程、重连循环。只在“还没切到远程”时重连 |
| `core/ui/src/components/RemoteConnectionPanel.vue` | 903 行 | 设备页。状态轮询、切换、扫码。名字、换票、阻塞问题 |
| `core/ui/src/composables/useCoreLiveComposerController.ts` | 约 700 行 | 发送与失败回执。失败有文案并保留输入，`canSubmit` 静默返回属正常拦截而非丢消息 |
| `core/ui/src/appServer/store.ts` | 约 600 行 | 连接生命周期、断线重连、`thread/gap` 重同步 |
| `core/ui/src/workbench/createWorkbench.ts` | 约 700 行 | 草稿按会话落 localStorage；切设备整页重载时附件托盘不保留 |
| `core/src/lamtools_core/app/live_hub.py` | 102 行 | 订阅队列。溢出转 `CoreAppEventGap` 并退订，由 `thread/gap` 兜住 |
| `core/src/lamtools_core/app/live_router.py` | — | 可靠通道上的 `thread/gap`，界面收到后重新 resume，设计正确 |
| `core/src/lamtools_core/app/live/threads.py` | — | `thread/started` 只发订阅者，另补 `session/created` 全量广播（已修） |
| `core/src/lamtools_core/app/http_agent_app.py` | — | hub 接线与 arrange 会话的全量广播（已修） |

## 已修（第一轮，提交 `1c6caf00`、`6896ff80`、`149bd053` 及之后）

| 编号 | 问题 | 修法 |
| --- | --- | --- |
| F1 | 桥自己 initialize，界面再发被拒成 `Already initialized`，模型/权限/插件全空 | 桥缓存握手答复，界面拿到同一份结果 |
| F2 | 事件泵另开一条没订阅的 socket，永远收不到 `item/delta` | 请求与事件共用同一条订阅过的 Core 连接 |
| F3 | 启动只拨一次，20 秒不通报废 | `keepRemoteAlive` 退避重试 + 回前台再试 |
| F4 | 切设备只存票据就重载，必然落回本机 | 先 `p2p_connect` 成功再 reload |
| F5 | 设备页用隧道状态猜当前环境 | 界面实际选择写 `sunday.p2p.active` |
| F6 | 电脑 Core 重启后 RPC 桥死掉但隧道还在，所有调用报错 | `is_dead()` + 下一条 RPC 就地重建，事件任务重新订阅 |
| F7 | 手机本机 Core 断线后复用死会话，只有重开应用才恢复 | `Session.alive`，死会话清掉并重连 |
| F8 | 16 MB 帧上限把长线程快照打成断线 | 提高到 64 MB |
| F9 | 并发拨号互相顶掉（PEER / PEER-CLOSED 抖动） | `ensureRemote` 单飞 + 补救预算 8 秒 |
| F10 | 完整票据写进 `p2p.log` | 默认只记前 24 位，`SUNDAY_P2P_LOG_TICKET=1` 才记全 |

## 本轮新发现

### A. 远程模式下附件与所有二进制 HTTP 都不通（高）

- 界面发 HTTP：`remoteTransport.ts` 的 `perform()` 把 `request.body` 用 `TextDecoder` 解成字符串，
  `JSON.parse` 失败就原样当文本发；`request.headers` 完全被忽略；响应体再 `JSON.stringify` 包一次，
  并把 `content-type` 固定成 `application/json`。
- 隧道那头：`proxy.rs` 只要有 body 就发 `Content-Type: application/json`；`parse_response()` 解析不了
  JSON 时返回 `{"raw": 有损 UTF-8 文本}`。
- 结果是：`POST /sessions/:id/attachments` 的 multipart 字节被当文本毁掉；`GET /attachments/:id/preview`
  回来的图片被有损解码成字符串；`POST /projects/:id/artifacts` 同理。界面侧只会显示「附件上传失败」。
- `picker.rs` 的文件头注释已经写明“`core_http` carries text bodies only”，所以这是**设计缺口**，不是偶发 bug。
  真机五步验收没有覆盖附件、预览、素材库。
- 修法（二选一，建议第二种）：
  1. 给帧协议加一个二进制载荷（长度前缀 + base64 或独立流），`core_http` 支持 `Content-Type` 与原始字节；
  2. 附件改走“路径引用”而不是字节：手机把文件放进一个双方都能看到的目录（远程时只能是电脑上的目录，
     所以远程附件本质上是选电脑上的文件），界面改用现有的 `/attachments/reference` 接口。
     远程模式下用户选的是**手机上的**文件，所以最终仍需要一条上传通道——第 1 种更根本。

### B. 「撤销设备」不生效（高，安全）

- `cli.rs` 在启动时 `TrustStore::load` 一次，之后每个 `ServerLink::accept` 用同一份 `Arc<Mutex<TrustStore>>`，
  从不重新读盘。
- 桌面 `p2p_host::p2p_revoke` 只改 `p2p-trust.json`。于是：撤销后那台设备**仍然能连**；`p2p_devices`
  列表里它已经消失，属于“看起来撤了”；更糟的是下一次有新设备接入时 `store.save()` 会把内存里
  仍然存在的旧条目写回文件，把撤销记录覆盖掉。
- 手机侧 `p2p_bridge::p2p_revoke` 同样只改本地文件，但手机从不 `accept`，影响面小。
- 修法：`accept` 每次判断前重新 `load` 一次（文件很小），或者给传输进程加一条“重新加载信任名单”的命令，
  由宿主在撤销后调用。前者更简单，也不依赖进程间通信。

### C. 断线要等一次 180 秒超时才被发现（高）

- `link.rs` 的 `alive` 只在读帧失败时置 false；`Frame::Ping/Pong` 定义了但没有任何一端主动发。
- 手机切 Wi-Fi、锁屏省电、VPN 起落时，QUIC 可能既不报错也不断开。此时 `Client::call` 会一直等到
  180 秒超时；期间的 `p2p_status` 走 busy 分支，回答 `connected: !dialing`，设备页显示「连接正常」。
- 修法：客户端每 10–15 秒发一次 `Ping`，超过 2 个周期没有 `Pong` 就置 `alive=false` 并回收连接；
  `p2p_status` 的 busy 分支改成读一个不依赖 `inner` 锁的原子标志（和 `connecting` 同样的做法）。

### D. 断线不通知界面，空闲时不会自动重连（高）

- `RemoteTransport.connect()` 无条件把状态设成 `connected`，之后隧道死了也不会变成 `disconnected`；
  `appServer/store.ts` 的重连只由 transport 报 `closed/error` 触发，远程模式永远等不到。
- `main-android.ts` 的 `keepRemoteAlive` 循环条件是 `while (!alreadyRemote())`，一旦切到远程就退出，
  所以远程期间没有任何后台重连。
- 后果：空闲断线后流式事件静默停止，界面上没有任何提示（与用户“显示和电脑断联了”“断联时不得
  静默丢消息”直接相关）；只有用户下一次操作触发 `RemoteTransport.request` 的补救拨号才恢复。
- 修法：宿主在 pump 退出时 `emit('p2p-progress', {phase:'lost'})`；`RemoteTransport` 监听并 `setState('disconnected')`；
  把 `keepRemoteAlive` 改成“只要界面在用远程就维持”的循环，而不是“只在还没切远程时重试”。

### E. 失败重放会重发非幂等请求（中）

- `RemoteTransport.request()` 在 `ensureRemote` 成功后把**同一条请求**再发一遍。
- `turn/start` 有 `client_message_id` 去重兜底（`turn_start.py:322` 明确写了幂等追加），但 `thread/start`
  没有：如果第一次其实已经在电脑上建好会话、只是回包在断线里丢了，重放会多出一条会话。
- 修法：只对读方法重放；写方法要么不重放（直接报错让用户重试），要么补一个客户端幂等键。

### F. 设备清单里电脑名字是十六进制（中，体验）

- `link.rs` 的 `Welcome` 只带 `id` 和 `trusted`，不带对端名字；界面只能 `rememberDevice(ticket, shortId(peer))`，
  于是手机设备页显示 `a1b2c3…4d5e`。
- 修法：`Welcome` 增加 `name`（服务端本来就知道自己的 `--name`），界面用它作为设备名。

### G. 「换一张」按钮换不了票据（中，诚实性）

- 桌面 `p2p_ticket` 走 `ensure_child`，传输进程活着时返回的是缓存票据；只有网络变化时 transport 才会打
  新 `TICKET` 行。所以用户点「换一张」，二维码内容原样不动。
- 修法：要么去掉这个按钮，要么实现真正的轮换（换 node key 代价太大；可行的是让 transport 生成一张
  带 nonce/有效期的票据，并在 Core 侧接受时校验）。

### H. `p2p_connect` 的预算包含排队等锁（中）

- `p2p_bridge.rs` 的 `attempt` 里第一件事是 `state.inner.lock().await`，而 `p2p_call` 会整段持锁。
  只要有一条慢调用在跑，点「切换」就会先排队，预算（默认 45 秒）到了报「连接超时」，实际上一次拨号
  都没发生，用户被引向错误的排查方向。
- 修法：拨号前用 `try_lock` 快速失败并给出「还有一条操作在进行」；或者把 client 放进
  `Arc<Mutex<Option<...>>>` 只锁取值，不锁整段调用。

### I. 拨号失败不清 `peer` 缓存（中，体验）

- `p2p_connect` 只在成功时写 `state.peer`；失败时旧值保留。`p2p_status` 于是返回
  `connected:false` + 上一台电脑的 `peer`，设备页那行会显示「未连接」但行内仍挂着旧 id。
- 修法：进入拨号就清空 `peer`，失败保持空。

### J. `send()` 那条路不可靠（中）

- `RemoteTransport.send()` 是 fire-and-forget 的 `invoke('p2p_call')`：没有错误处理，也不等待，
  和并发 `request()` 之间没有顺序保证；`type:'response'` 的消息没有 `method`，会被直接丢掉。
- 目前实际只用于 `initialized` 之类的通知，影响有限；但反向 RPC（服务端请求客户端）在远程模式是
  走不通的。以后要加“服务端向客户端要东西”的能力，需要单独一条帧类型。

### K. 桌面配对命令阻塞（中，体验）

- `p2p_ticket` / `p2p_serve_start` 是同步命令，内部最长阻塞 30 秒读子进程 stdout（还要等中继 10 秒）；
  `p2p_qr` 每渲染一次二维码就 `spawn` 一个 `sunday-p2p` 进程。
- 同步命令占着 IPC 线程执行，第一次打开「设备连接」会明显卡住整个窗口。改成 `async fn` +
  `spawn_blocking`，二维码在宿主内缓存（票据不变就不重算）。

### L. 请求串行（第一轮 P1-4，仍在）

- `ServerLink::serve` 逐条 `handler().await`；手机宿主 `p2p_call` 又整段持 `inner` 锁。界面启动时并发的
  `config.models.list` / `settings.get` / `thread/outline` 实际一条一条跑，任何一条慢都挡住后面。
- 修法不变：`serve` 把每条 Call 派独立任务（写帧共用一把锁），宿主侧把 client 的取用从整段调用里挪出来。

### M. 一次只接受一台设备（第一轮 P1-5，仍在）

- `cli.rs` 的 `loop { accept().await; serve().await }` 在第一台断开前不会再 accept。两台手机无法同时连。

### N. 事件 Lagged 静默丢帧（第一轮 P2-9，仍在）

- `cli.rs` 里 `Err(RecvError::Lagged(_)) => continue`。注意 Core 自己那侧已经把 hub 溢出转成可靠通道上的
  `thread/gap`（`live_hub.py` + `live_router.py`），界面也会 `thread/resume` 重同步——**丢的是 p2p 这条腿**。
- 修法：Lagged 时给对端补发一条 `thread/gap`（参数带当前 thread_id），界面就能走已有的重同步逻辑。

### O. 首次连接自动信任（第一轮 P2-7，待决策）

- 票据没有有效期，泄露一次就永久可用；配合 B（撤销失效），目前唯一的止损手段是把传输进程停掉再改文件。
- 建议：先修 B，再决定是否加电脑端确认。

### P. 其它（低）

- `identity.rs` 写密钥、`trust.rs` 写名单都用默认文件权限；Windows 上同用户其它进程可读，可冒充电脑。
- `p2p.log` 有两个写者（transport 自己 `diary()` + 宿主日志线程），追加交错，排障时会出现半行。
- `proxy.rs` 的 32 MB 上限在 `read_to_end` 之后才检查，超大响应会先占内存。
- `p2p_scan` 一次性 `busy` 最长 120 秒且没有取消按钮。
- 设备页的 `activeId` 是读 `localStorage` 的 computed，没有响应式依赖；切换后到 reload 之间徽标不更新。
- 切设备靠整页 reload，输入框文字有 localStorage 草稿，但**未发送的附件托盘会丢**。
- 桌面 Core 启动时被 `env_remove("LAMTOOLS_CORE_API_TOKEN")`，所以本机 127.0.0.1 的 Core 对所有本机进程开放；
  说“p2p 是唯一入口”只在有令牌的部署里成立。

## 未在真机验证（本轮审查无法覆盖）

- 远程模式上传附件、预览图片（按 A 的判断会失败，待真机确认错误文案是否可读）。
- 断线后的表现：现在预期是「没有提示，下一次操作才恢复」。
- 悬浮环长按拖动、系统小窗、前后台切换、重启后持久化。
- 无线调试已关闭（5555/34127/38935 均拒绝连接），所有真机复验被阻断。

## 修复顺序建议

1. **B**（撤销设备）——安全，改动小，先止血。
2. **C + D**（心跳 + 断线上报 + 远程期间保持重连）——直接对应「显示和电脑断联了」。
3. **A**（远程二进制通道）——决定“远程能不能发附件”，需要一次协议改动，单独一轮做。
4. **L + M**（请求串行、单设备）——结构问题，一起改 `serve`。
5. **N、E、F、G、H、I、J、K** 按触碰频率排。
6. **O、P** 与产品决策一起处理。
