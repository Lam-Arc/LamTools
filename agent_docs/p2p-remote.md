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

## 还没做

1. 接进两端宿主：桌面（`core/desktop/src-tauri`）与 Android 宿主各暴露一组命令
   （票据、连接、调用、事件、撤销），UI 的"远程连接"页接这组命令。
2. 远程会话界面：手机连上电脑后，用同一条通道把 Core 的 JSON-RPC 搬过去，会话列表、
   发消息、审批、事件订阅全部复用现有共享 UI，只换 transport。
3. 二维码渲染与扫码，本地/远程模式切换与状态展示。
4. 自定义 relay 配置入口。
5. `events()` 还只是个占位：事件帧已经在协议里，尚未接到调用方。
