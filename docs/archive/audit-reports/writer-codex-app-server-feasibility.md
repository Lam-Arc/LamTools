# Writer Codex App Server Feasibility

更新时间：2026-06-24

## decision

writer-subset

## reason

不能把 Writer 当前主链路直接桥接到官方 Codex app-server 作为本轮整改的落地路线。官方 Codex app-server 的业务模型是正确上限：JSON-RPC 双向连接、thread/turn/item、server request 审批、streamed events、history/read/snapshot。Writer 必须对齐这个模型。

但本机和当前 Writer 产品边界同时存在阻塞项：本机 `codex app-server` 不可执行，无法生成当前版本 schema，也无法启动可托管的 loopback app-server；Writer 还保留自有 provider 配置、WriterKit 工具体系、Writer SQLite 会话和现有产品界面。如果直接桥接官方 app-server，短期内无法证明认证、工具、历史、work_root 与 Writer session 的完整映射。

因此本轮进入 Writer App Server 子集实现：只实现 Writer 需要的最小 app-server 风格协议和事件模型，保持 OpenAI/Codex 的 thread/turn/item/server-request 语义，不继续沿用 SSE、DB polling、本地 pending、本地 queue 和 live/replay 双投影作为产品主链路。

## blocking_items

1. 本机官方 CLI 阻塞：`codex app-server --help`、`codex app-server generate-ts --out tmp/codex-app-server-schema`、`codex app-server --listen ws://127.0.0.1:7005` 均返回 `Access is denied`。
2. schema 生成阻塞：官方 schema 必须由当前 Codex 版本生成；本机命令不可执行，因此无法把 Writer 前端绑定到官方当前版本 schema。
3. 托管进程阻塞：无法启动官方 app-server，也就无法完成 readiness、health、auth、bounded queue、turn event 的本机验证。
4. 产品边界阻塞：Writer 现有运行链路依赖 Writer 自有 provider 配置、WriterKit、工具审批、work_root、SQLite session、artifact 和 queue 语义；直接切换到官方 history/thread 需要迁移策略和工具接入证明。
5. 整改前旧链路仍在产品主路：当时代码大量命中 `/api/sessions/{id}/chat` SSE、`/sessions/events`、`/queued-inputs` REST、`sseStore.activityFeed`、`sseStore.running`、`projectTranscriptSnapshot`、`WriterQueuedInput` 等旧主链路入口。该项是进入 Writer App Server 子集实现的原始证据，不代表当前代码状态。

## evidence

### 官方资料

- OpenAI Codex app-server 文档确认它面向 rich clients，提供 authentication、conversation history、approvals、streamed agent events。
- 官方协议是 JSON-RPC 2.0 双向通信；支持 stdio、WebSocket、Unix socket 等传输。
- 官方核心对象是 Thread、Turn、Item；turn 运行中通过 `item/started`、`item/completed`、`item/agentMessage/delta`、tool progress、`turn/completed` 等通知流式推送。
- 官方审批是 server-initiated JSON-RPC request，客户端返回 decision，服务端继续或拒绝工作，并最终用 `item/completed` 收口。
- 官方 WebSocket 模式有 bounded queues；ingress 满时返回 `-32001 "Server overloaded; retry later."`，客户端应指数退避并加 jitter。

来源：`https://developers.openai.com/codex/app-server`

### 本机验证

```text
PS E:\LamTools> codex app-server --help
Program 'codex.exe' failed to run: Access is denied
```

```text
PS E:\LamTools> codex app-server generate-ts --out tmp/codex-app-server-schema
Program 'codex.exe' failed to run: Access is denied
```

```text
PS E:\LamTools> codex app-server --listen ws://127.0.0.1:7005
Program 'codex.exe' failed to run: Access is denied
```

`Get-Command codex -All` 显示命中的是 WindowsApps 打包路径：

```text
C:\Program Files\WindowsApps\OpenAI.Codex_26.616.9593.0_x64__2p2nqsd0c76g0\app\resources\codex
C:\Program Files\WindowsApps\OpenAI.Codex_26.616.9593.0_x64__2p2nqsd0c76g0\app\resources\codex.exe
```

### 整改前 Writer 旧链路证据

阶段 0 时 `rg` 扫描产品代码命中以下主链路：

- 前端 `members/writer/frontend/src/stores/sse.ts` 仍维护 `activityFeed`、`startStream`、`writer_part`、`writer_reply_delta` 等 SSE 状态。
- 前端 `members/writer/frontend/src/views/CoreWorkbenchView.vue` 仍读取 `sseStore.running`、`sseStore.activityFeed`、`transcriptSnapshot`、`queuedInputs`，并调用旧 stream 和 queue REST。
- 前端 `members/writer/frontend/src/api/index.ts` 仍暴露 `/api/sessions/{session_id}/chat`、`/api/sessions/events`、`/queued-inputs` 主链路方法。
- 后端 `members/writer/backend/app/routers/session.py` 仍暴露 `/sessions/events`、`/sessions/{session_id}/queued-inputs`、`/sessions/{session_id}/chat`。
- 后端 `members/writer/backend/app/services/transcript_service.py` 和 `queued_input_service.py` 仍支撑 DB projection / queue REST 路径。

这些证据说明当时的问题不是单个 UI bug，而是多条显示和状态链路并行。后续整改按 Writer App Server Implementation Plan 从阶段 1 执行。

### 当前复核状态

2026-06-24 后续整改已进入 `writer-subset` 路线并完成浏览器主链路验收。当前产品前端不再使用旧 SSE store、旧 `/chat` SSE、旧 `/queued-inputs` REST、旧 transcript projection 作为实时显示主链路。CLI/TUI 仍保留 legacy-shaped adapter 以承接 app-server 事件，但不参与浏览器主显示链路。
