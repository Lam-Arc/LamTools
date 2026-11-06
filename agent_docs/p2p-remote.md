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

票据是一段文本：`sunday1:` + base64url(JSON)，内容是节点 id 加上当时已知的地址
（relay 或局域网地址）。二维码只是这段文本的另一种呈现，不需要第二套数据。

第一次连接即配对：被叫方把拨号方写进 `p2p-trust.json`，之后静默。撤销就是删掉那条，
下一次握手直接拒绝。连接本身已经是 TLS + 节点公钥认证，所以名单就是信任的全部内容，
没有可以重放的令牌。

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
  读它的 `TICKET`/`READY` 两行，把票据交给 UI；停止就是杀掉这个进程。
- 手机：宿主内直接链接 `sunday-p2p`，命令是 `p2p_ticket / p2p_connect / p2p_call / p2p_status /
  p2p_disconnect / p2p_devices / p2p_revoke`。
- 桌面命令：`p2p_ticket / p2p_serve_start / p2p_serve_stop / p2p_status / p2p_devices / p2p_revoke`。
- UI：`RemoteConnectionPanel`，桌面出票据与接受连接，手机粘贴票据连接；两边都能看/撤销可信设备。

传输程序的位置：`SUNDAY_P2P_BIN` 优先，其次应用同目录，最后开发目录
`core/p2p/target/{release,debug}`。打包版需要把 `sunday-p2p.exe` 放进应用旁边。

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
  中继只按节点 id 转发加密流量，不需要账号。

## 还没做

1. 扫码：二维码已经能画，缺的是用相机扫回来（现在是复制票据粘贴）。
2. 删除旧的 `core/desktop/src-tauri/src/remote/`：**暂缓，有依赖**。Python CLI 的
   `cli_commands/server.py` 通过 `lamtools-remote-control.json` 连桌面端的控制端口，
   而那个端口由 `remote/control.rs` 提供；`core/desktop/src/main.ts` 也还在调
   `remote_*` 命令。要删得先把 CLI 这条控制路径迁到别处，不能一刀切。
3. 实体设备上的整链验收：手机连电脑、看会话、发消息、收审批。
