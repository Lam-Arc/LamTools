# 连接、配对、投递链路审查

第一轮：2026-11-08（功能打通后的结构性问题）
第二轮：2026-11-09（全量复审，逐文件通读）
第二轮修复：2026-11-09，提交 `6822b447`

> 读日志与源码时注意：命令输出的脱敏层会把 `Bearer {token}\r\nConnection: ...` 这类片段替换成
> `Bearer [REDACTED] ...`。判断字段是否真的存在，要用 `od -c` 或 `grep -c` 交叉验证，不要直接相信
> 被改写过的行。本轮 `proxy.rs` 就因此被误判过一次，核对后源码是正确的。

## 结论摘要

第二轮找到的三块「用户会直接撞上」的缺口都已在 `6822b447` 修掉：远程模式下附件与二进制 HTTP、
撤销设备不生效、断线只能靠一次 180 秒超时才发现。其余结构性问题（请求串行、事件丢帧、重放边界、
设备名、「换一张」）同批修完。仍然剩下的只有一项产品决策（首次连接自动信任）和几项低优先级的
加固。

## 审查范围

| 文件 | 结论 |
| --- | --- |
| `core/p2p/src/link.rs` | 帧协议、握手、心跳、并发处理。已修 |
| `core/p2p/src/rpc.rs` | Core JSON-RPC 桥，initialize 缓存与死桥重建正确 |
| `core/p2p/src/events.rs` | 旧事件泵（只在没有 RPC 桥时启用） |
| `core/p2p/src/identity.rs` | 节点密钥、relay 配置；密钥文件权限默认（未改） |
| `core/p2p/src/ticket.rs` | 票据编解码；无有效期（产品决策） |
| `core/p2p/src/trust.rs` | 可信名单，已加 `reload()` |
| `core/p2p/src/qr.rs` / `scan.rs` | 二维码生成与解码，无问题 |
| `core/p2p/src/proxy.rs` | REST 转发，已改为字节透传 + chunked 解码 |
| `core/p2p/src/bin/cli.rs` | 服务端：多设备并发接受、每条调用独立任务、`thread/gap` 补帧 |
| `core/android-host/src-tauri/src/p2p_bridge.rs` | 手机宿主：不再整段持锁、存活标志、lost 事件、Lagged 兜底 |
| `core/android-host/src-tauri/src/client.rs` | 本机 Core socket，死会话重建正确 |
| `core/android-host/src-tauri/src/picker.rs` | SAF 桥，路径交换正确 |
| `core/desktop/src-tauri/src/p2p_host.rs` | PC 宿主：异步命令、守护线程、二维码缓存 |
| `core/ui/src/transport/remoteTransport.ts` | 远程通道：二进制、状态上报、重放边界 |
| `core/ui/src/transport/remoteCodec.ts` | 新增：编解码与重放判断，带单测 |
| `core/ui/src/app/remoteSession.ts` | 票据/设备清单，单飞拨号正确 |
| `core/ui/src/core-app/main-android.ts` | 启动与常驻重连循环 |
| `core/ui/src/components/RemoteConnectionPanel.vue` | 设备页 |
| `core/ui/src/composables/useCoreLiveComposerController.ts` | 发送与失败回执，失败有文案且保留输入 |
| `core/ui/src/appServer/store.ts` | 连接生命周期、断线重连、`thread/gap` 重同步 |
| `core/ui/src/workbench/createWorkbench.ts` | 草稿按会话落 localStorage |
| `core/src/lamtools_core/app/live_hub.py` | 订阅队列，溢出转 `thread/gap` |
| `core/src/lamtools_core/app/live_router.py` | 可靠通道上的 `thread/gap` |
| `core/src/lamtools_core/app/live/threads.py` | `session/created` 全量广播 |
| `core/src/lamtools_core/app/http_agent_app.py` | hub 接线与 arrange 广播 |

## 第二轮修复明细（`6822b447`）

| 编号 | 问题 | 修法 | 位置 |
| --- | --- | --- | --- |
| A | 远程模式下附件、图片/PDF 预览、素材库全部不可用：隧道只搬文本 | `core_http` 改成 `{method, path, headers, body_b64}`，服务端用新增的 `call_core_raw` 原样转发字节与 Content-Type，回答按字节回传（含 chunked 解码） | `proxy.rs`、`bin/cli.rs`、`remoteTransport.ts`、`remoteCodec.ts` |
| B | 撤销设备不生效：内存不重读，而且首次连接会自动信任，删掉名单等于没做 | `TrustStore` 增加撤销名单，握手前重读并在自动信任之前检查；被拒时仍发握手帧，对端能看到人话；设备页可以重新允许 | `trust.rs`、`link.rs`、`bin/cli.rs`、`p2p_host.rs`、`RemoteConnectionPanel.vue` |
| C | 网络静默断开时，下一次调用要等 180 秒超时 | 客户端每 12 秒 `Ping`，40 秒没有 `Pong` 判死；服务端 120 秒没有帧就收掉连接 | `link.rs` |
| D | 断线不通知界面，远程期间没人重连 | 宿主监听存活标志并 `emit('p2p-progress',{phase:'lost'})`；`RemoteTransport` 据此把状态改成 `disconnected`（`store.ts` 会安排重连）；`keepRemoteAlive` 改成只要还记着票据就一直守着 | `p2p_bridge.rs`、`remoteTransport.ts`、`main-android.ts` |
| E | 失败后重放会重发非幂等请求 | 只重放读操作（GET、`thread/resume`/`read`/`list`/`outline`、`config.`/`settings.`/`workspace.`），写操作直接报「没有确认送达」 | `remoteCodec.ts`、`remoteTransport.ts` |
| F | 手机设备清单里电脑名是十六进制 id | `Welcome` 增加 `name`（老服务端缺这个字段时按空串处理） | `link.rs`、`p2p_bridge.rs`、`RemoteConnectionPanel.vue` |
| G | 「换一张」按钮换不了票据 | 去掉这个按钮；网络变化时 transport 仍会自己打新票据 | `RemoteConnectionPanel.vue` |
| H | 拨号的预算被排队等锁吃掉，报假的「连接超时」 | 拨号单独串行（`dialing_gate`），不占用调用用的 `inner` 锁 | `p2p_bridge.rs` |
| I | 拨号失败后设备页仍挂着上一台的 peer | 拨号开始就清空 peer 缓存 | `p2p_bridge.rs` |
| K | 桌面配对命令阻塞 IPC 线程，每张二维码启一个进程 | 命令改 `async` + `spawn_blocking`；二维码按票据缓存 | `p2p_host.rs` |
| L | 请求串行：服务端逐条 await，手机宿主整段持锁 | 服务端每条 Call 独立任务（写帧共用一把锁）；`Client::call` 改 `&self` + 原子 id，宿主只取一次 `Arc` 就放锁 | `link.rs`、`p2p_bridge.rs` |
| N | 事件丢帧被静默吞掉 | 服务端 `Lagged` 时补一条 `thread/gap`（带当前订阅的会话 id），界面走已有的重同步；手机侧转发任务不再因 `Lagged` 退出，同样补 `thread/gap` | `bin/cli.rs`、`p2p_bridge.rs` |
| P | 响应大小上限在读完之后才检查 | 改成 `Read::take` 先限流再读 | `proxy.rs` |

**修的过程中新发现的**：手机宿主的事件转发原来是 `while let Ok(event)`，广播通道一旦 `Lagged`
整个任务就退出，手机从此只发得出、收不到，而且不算断线。已在同一批修掉（见 N）。

**更正上一轮的一个误判**：`P1-5`「一次只接受一台设备」在当时的代码里已经不成立——`cli.rs`
的 `accept` 之后 `serve` 已经是 `tokio::spawn` 出去的，主循环会继续接受下一台。本轮只补了
服务端并发处理，没有改接受逻辑。

## 仍然存在

| 编号 | 问题 | 说明 |
| --- | --- | --- |
| O | 首次连接自动信任 | 票据没有有效期，拿到即完整控制权。主推荐先靠「撤销立即生效」（已修）止血；是否加电脑端确认需要产品决策 |
| J | 反向 RPC（服务端请求客户端）在远程模式走不通 | 应答帧没有 method，隧道的帧必须有方法名。当前只有 `initialized` 这类通知走 `send()`，没有实际影响 |
| — | 身份私钥与 trust 文件用默认权限 | Windows 上同用户其它进程可读；需要时再加 ACL |
| — | `p2p.log` 有两个写者 | transport 自己 `diary()` 与宿主日志线程追加交错，排障时可能出现半行 |
| — | 切设备靠整页 reload | 输入框有 localStorage 草稿，未发送的附件托盘会丢 |
| — | `p2p_scan` 一次性 busy 最长 120 秒且无取消 | 体验问题 |
| — | 桌面 Core 无令牌 | `configure_internal_backend_access` 移除了 `LAMTOOLS_CORE_API_TOKEN`，本机 127.0.0.1 的 Core 对所有本机进程开放；「p2p 是唯一入口」只在有令牌的部署里成立 |

## 验证记录

- `core/p2p`：`cargo check --all-targets`、`cargo test`（含 `reload_picks_up_a_revocation_written_by_the_host`、
  `decodes_a_chunked_body`、`binary_bodies_survive_untouched`）全绿；`cargo build --release` 产出
  13,160,960 字节的 `sunday-p2p.exe`。
- `core/android-host`、`core/desktop/src-tauri`：`cargo check` 通过。
- `core/ui`：`vue-tsc --noEmit` 在本次改动的文件上没有错误（仓库里其它文件的既有错误与本轮无关）；
  `vitest run tests/remote-codec.test.ts` 3 项通过。
- 端到端（真实二进制、真实隧道、真实 Core）：`ping` → `pong`；`core_http GET /projects` 返回 status 200 与可解码的 JSON；
  撤销一台 `Probe3` 之后再连被拒（对端看到「可能已被撤销授权」），重新允许后又能连上。
- 真机：**尚未验证**。无线调试当前是关的（5555/34127/38935 均拒绝连接），新 APK 装不上。
  需要在真机上复验：远程附件上传与预览、断线提示与自动重连、切换设备、撤销设备。
