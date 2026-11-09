# 连接、配对、投递链路审查（2026-11-08）

范围：`core/p2p/src/*`（隧道、RPC 桥、事件泵、票据、信任）、`core/android-host/src-tauri/src/{p2p_bridge,client}.rs`（手机宿主）、
`core/ui/src/transport/*`（三条通道）、`core/ui/src/app/remoteSession.ts`、`core/ui/src/core-app/main-android.ts`、
`core/ui/src/components/RemoteConnectionPanel.vue`（配对与切换）。

结论先说：链路的**功能**是通的（真机远程五步验收已过），但有四类结构性问题会让「连着却像断了」或
「必须退出应用重进」，其中两条是 Core 侧进程重启后链路不自愈。

## P0 进程重启后链路不自愈

### 1. 电脑端 Core 重启后，手机远程永久报错，直到手机重连

`core/p2p/src/bin/cli.rs` 在每次 `ServerLink::accept` 之后创建一次 `CoreRpc`（`CoreRpc::connect`），
整个隧道连接期间复用。`core/p2p/src/rpc.rs` 的 reader 任务在 Core 的 WebSocket 断开时 drain 掉所有
等待者并退出，writer 在下一次写失败后 `break`，`jobs` 的接收端随之消失。

于是 Core 重启后（换端口，旧 socket 全断）：
- 这条隧道的 RPC 桥已经死了，但 `ServerLink::serve` 还在正常收发帧；
- 每条 `Call` 都走到 `bridge.call(...)`，得到「RPC 通道已关闭」；
- 手机端的 `p2p_status` 仍回答 `connected: true`（隧道本身没断），界面的自动重连不会触发；
- 用户看到的是：手机连着电脑，但项目、模型、发消息全部报错，只有重新配对才恢复。

用户每次更新或重启桌面端都会踩到。事件通道在这一版之后与 RPC 共用同一条 Core 连接，所以断的
时候事件也一起停（比之前更难察觉）。

修法：reader 退出时把桥标记为 dead；`bridge.call` 发现 dead 就先 `CoreRpc::connect` 重建（带退避），
重建失败才把错误交给调用方。或者在 `link.serve` 里检测 Core 可达性，不可达时重新建桥。

### 2. 手机本地 Core 断线后，应用内所有调用永久失败

`core/android-host/src-tauri/src/client.rs`：`pump()` 退出时只 `session.fail_pending()`，
**没有清掉 `self.session`**。之后的 `ensure_session()` 直接返回这条死会话，`call_on` 往已关闭的
`outbound` 发消息，得到 `the core connection is closed`。只有 `retarget()`（`core_start` 再次调用）
会清会话。

表现：本地 Core 偶发崩溃或被系统回收后，手机上「本机」模式的所有操作都失败，杀掉应用重开才恢复。

修法：`pump` 退出时标记会话失效（或直接清 `session`）；`ensure_session` 检查存活，死了就重建并
重新握手（`handshake` 缓存也要一起清）。

## P1 大消息、并发、多设备

### 3. 16 MB 帧上限会把长会话直接断掉

`core/p2p/src/link.rs`：`MAX_FRAME_BYTES = 16 * 1024 * 1024`，`write_frame` 超限直接 `bail`。
Core 的 `thread/resume` 快照在长线程上可以达到几十 MB（代码里注释提到过 48 MB 级的解析，
`appServer/store.ts` 为避免它专门传 `include_snapshot: false`）。只要有一条回复或一次快照推送
超过 16 MB，服务端 `serve` 返回 `Err`，整条隧道关闭。

修法：把上限提到与 Core 的 `max_message_bytes` 同一量级（Core 侧是 4 MB 的单帧限制，但快照
分页不受它约束），或者对大结果做分块传输；至少让超限变成「这条 RPC 失败」而不是「连接关闭」。

### 4. 请求串行：一条慢 RPC 卡住界面其余加载

`ServerLink::serve` 是 `loop { read_frame → handler().await → write }`，一次只处理一条 Call。
手机宿主侧 `p2p_call` 又用 `&mut Client` 串行化。界面启动时并发发起的
`config.providers.list` / `config.models.list` / `settings.get` / `thread/outline` 实际是一条一条跑。
任何一条慢（Core 冷启动、插件扫描）都会挡住后面的。

修法：`serve` 把每条 Call 派给独立任务（写帧仍走同一把锁），回包顺序按 id 匹配，不需要保序。

### 5. 一次只接受一台设备

`cli.rs` 的 `loop { accept().await; serve().await }`：第一台设备连上后，直到它断开才会 accept 下一台。
用户有两台手机（或手机 + 平板）时，第二台会一直「连不上」。

修法：accept 后 spawn 一个任务跑 `serve`，主循环继续 accept。

### 6. 并发拨号互相打断

现在有三处会发起拨号：启动阶段的 `ensureRemote`、后台的 `keepRemoteAlive` 循环、
`RemoteTransport.request` 失败后的 `ensureRemote(1200)`。`p2p_connect` 每次都会先
`inner.client.take() + previous.close()` 再拨，而且整个拨号期间持有 `inner` 锁。

结果就是之前日志里看到的 `PEER` / `PEER-CLOSED` 抖动：A 刚连上，B 拨号把它关掉，B 又超时。

修法：拨号做单飞（同一时刻只允许一次，后来者等结果而不是重拨）；`RemoteTransport` 的失败重试
交给上层的单一重连循环，不要在每次请求失败时自己拨。

## P2 安全与细节

### 7. 票据就是完整控制权，而且明文写了日志

拿到票据的人可以调用 Core 的任意 RPC/REST，包括执行工具（远程「全权」由票据持有者的会话权限决定）。
`cli.rs` 把完整票据写进 `p2p.log`（`diary(TICKET ...)`），桌面宿主也会把传输进程输出追加到同一份日志。
日志一旦发给别人（排障、贴群里），等于交出控制权。

另外 `link.rs` 的首次连接是**自动信任**：任何持有票据的设备第一次连接就会被写进 trust store，
之后设备清单里多一条。撤销设备只能撤掉已经连过的那台，不能撤回泄露的票据。

修法：日志里票据只留前 12 位；首次连接要求电脑端确认（或票据带有效期/一次性）。

### 8. 状态查询在长调用期间会说「已连接」

`p2p_bridge.rs`：`p2p_call` 持有 `inner` 锁，`p2p_status` 拿不到锁时走 busy 分支，回答
`connected: !dialing`。如果这是有一条 180 秒的调用卡在死连接上，界面会显示「连接正常」。

修法：busy 分支也读一次 client 存活（把 alive 放到不依赖 inner 锁的位置，例如独立的 `Arc<AtomicBool>`）。

### 9. 事件缓冲溢出会静默丢帧

`rpc.rs` 的 `broadcast::channel(4096)`，`RecvError::Lagged` 时 `continue` 丢最旧的。流式增量丢失
后界面内容会缺一段，直到下一次快照；而快照只在少数事件上触发。

修法：Lagged 时给界面补一个「需要重新同步」信号（例如转成 `thread/gap`），让它主动重新 resume。

### 10. 其它

- `Client::call` 写帧失败时 pending 里残留一个 sender（reader 退出会 drain，影响小）。
- `Hello` 只有 name，没有协议版本；将来改帧协议没有协商余地。
- 桌面端既可能被 `p2p_serve_start` 拉起，也可能被手动启动一个（我排障时就起过一个），两个进程会写同一份
  `p2p.log` 和同一份 trust store，靠文件锁之外没有互斥。

## 已经修掉的（本轮）

- 桥自己发过一次 `initialize`，界面再发就被 Core 拒成 `Already initialized` → 模型、权限、插件全空。
- 事件泵另开一条没订阅任何会话的 socket，永远收不到 `item/delta` → 手机发得出、看不到回复。
- 启动只拨一次，20 秒没通就再也不试 → 必须重开应用。
- 切换设备只存票据就重载，重载时通道没通必然落回本机；加上启动阶段的 sessionStorage 去重标记挡住第二次
  切换 → 「点切换，转一圈，还在本机」。
- 设备页用隧道状态猜「当前环境」→ 设备页说本机、界面其实在电脑上。

## 修复进度

已修（提交 `1c6caf00` 及之后）：

- **P0-1**：`cli.rs` 把 RPC 桥放进 `Mutex<Option<Arc<CoreRpc>>>`，`CoreRpc` 暴露 `is_dead()`；下一条 RPC 发现桥死了
  就地重建（`RPC-CHANNEL REBUILT` 会写进日志），事件任务换成「重新取桥再订阅」的循环。
- **P0-2**：`Session` 加 `alive` 标志，pump 退出时置 false；`ensure_session` 发现死会话就清掉会话与握手缓存并重连。
  （克隆会话时先落在独立语句里，避免持锁重入死锁。）
- **P1-3**：帧上限 16 MB → 64 MB，覆盖长线程快照；超限仍会拒绝，但不再对正常回复误伤。
- **P1-6**：`ensureRemote` 改成单飞（并发调用共享同一次拨号），`RemoteTransport` 失败补救的预算从 1.2 秒提到 8 秒，
  不再出现「A 刚连上被 B 顶掉」的 PEER/PEER-CLOSED 抖动。
- **P2-7**：票据写日志默认只留前 24 位，需要完整票据时开 `SUNDAY_P2P_LOG_TICKET=1`。

待办（按建议顺序）：

1. **P1-4** 请求串行：`ServerLink::serve` 把每条 Call 派给独立任务（写帧仍共用一把锁）。
2. **P1-5** 单连接 accept：accept 后 spawn，主循环继续等下一台设备。
3. **P2-9** 事件缓冲 Lagged 丢帧：转成 `thread/gap`，让界面主动重新 resume。
4. **P2-8** `p2p_status` 的 busy 分支也要看 client 存活（要把 alive 从 `inner` 锁里拿出来）。
5. **P2-7 的确认部分**：首次连接自动信任，票据泄露无法通过撤销设备止血；建议首次连接要电脑端确认一次。
