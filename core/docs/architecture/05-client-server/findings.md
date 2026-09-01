# 桌面端 / 界面 / 应用服务器架构发现

分析基线：`https://github.com/Lam-Arc/LamTools.git`，revision `5c1371e717dfa86e125665f7669526d758ad5bce`。本页回答“表示层、传输层、后端 和 Core 状态 如何解耦”。

## 边界

- 表示层：Vue Workbench、UI 投影 store、Tauri window/shell 和用户交互。
- 传输层：App Server Client、HTTP 路由、FastAPI mounting、JSON-RPC 实时 WebSocket protocol。
- 后端/应用层：`CoreLiveOperationHost`、会话/项目 operations、***运行时任务注册表***、LLM/工具/插件 装配。
- Core 运行时：***核心循环内核***（`CoreLoopKernel`） 与 运行时/智能体 ports。
- 持久化：***核心应用数据库***、***事件存储***、***快照存储*** 和 ***运行时状态*** adapter。

Tauri 当前是真正的 Shell：Rust 侧选择并启动本地 后端，`core/desktop/src/main.ts` 通过 `get_api_base` 注入 `window.__LAMTOOLS_API_BASE__`，再挂载 Vue App。它不应成为业务层。

## 职责

- Vue UI 负责输入、交互、窗口体验和把 投影 渲染成组件。
- ***核心应用服务器客户端***（`CoreAppServerClient`） 负责 WebSocket 建连、JSON-RPC 请求/响应、服务端 请求 响应、快照/事件 回调和 URL 组装。
- FastAPI 负责 app 装配、HTTP route 挂载、启动/关闭 与本地 API adapter。
- `live_router.py` 负责 origin 校验、初始化、连接生命周期、outbound queue、事件 coalescing 和 重连/恢复 协议。
- 运行时 负责真正的 轮次 执行；事件 Hub 把 运行时 事件广播给 transport/客户端。
- UI store / workbench 投影 负责把 事件/快照 变成可渲染状态，不应重算 Core 的完成、权限或恢复语义。

## 依赖

当前主链路是：

`Vue UI → CoreAppServerClient → FastAPI / live_router → CoreLiveOperationHost → CoreLoopKernel`

回流链路是：

`CoreLoopKernel → EventHub → live_router → CoreAppServerClient → UI projection`

这是合理的 inbound/出口适配器 形态。`live_router.py` 已把连接背压、消息大小、浏览器 Origin、runItem coalescing 与 快照 trigger 放在传输边界，说明 UI 不需要直接知道 运行时 的内部 loop。

## 耦合

1. `http_agent_app.py` 同时承担 FastAPI factory、启动/关闭、DB 打开、插件 生命周期、会话 store、operations、路由 和 desktop-plugin endpoint，是当前最大的 后端/应用层 混合点。
2. UI 的 `selectors.ts`、`messageParts.ts` 和 `workbenchProjection.ts` 对事件与 快照 做 normalization；这必须保持为 transport 投影，不应复制 运行时 决策。
3. API 路径、JSON-RPC method、快照/事件 模式 同时被 Python 服务端 与 TypeScript 客户端 消费，协议稳定性是跨语言耦合点。
4. Tauri 的 `get_api_base`、file 来源、window commands 和 external URL 是合理的 host 能力，但若更多 Core 逻辑进入 Rust/desktop host，会重新形成第二个业务层。

## 风险

- P1：`http_agent_app.py` 的 application 装配 与 transport adapter 混合，任何 UI endpoint 变化都可能影响 运行时/持久化 启动。
- P1：API/WS contract 没有独立的版本化 DTO/夹具 层时，Python 事件 信封 与 TypeScript 投影 的演进需要同步发布。
- P2：UI 投影 与 Core 快照 都保存相似的 turn/item/状态 信息；若语义判断散落到 UI，未来多客户端会出现不一致。
- P2：Tauri、plain browser 和 packaged 后端 的 API base / file 来源 分支需要保持同一协议测试矩阵。

## 建议

1. 抽出 ***核心应用宿主***（`CoreApplicationHost`）：只负责依赖装配和生命周期；FastAPI factory 只负责 route 挂载，Tauri 只负责 host 能力。
2. 为 HTTP/WS 建立独立的 protocol package、模式 夹具 和 兼容性 tests；UI 客户端 只消费 protocol 投影。
3. 明确 快照 是 装载/读取模型，实时 事件 是增量传输；UI store 不重新决定 completion、审批、权限 或 恢复。
4. 把 desktop-only operations 限制在 host 能力 API；新增 Web UI 时复用同一个 传输层 contract。

## 证据

- `core/desktop/src/main.ts`
- `core/desktop/src/desktopPluginHost.ts`
- `core/src/lamtools_core/app/http_agent_app.py`
- `core/src/lamtools_core/app/live_router.py`
- `core/src/lamtools_core/app/live_hub.py`
- `core/src/lamtools_core/app/live_protocol.py`
- `core/src/lamtools_core/app/live_operations.py`
- `core/ui/src/appServer/client.ts`
- `core/ui/src/appServer/protocol.ts`
- `core/ui/src/appServer/store.ts`
- `core/ui/src/appServer/workbenchProjection.ts`
- `core/src/lamtools_core/http/routes.py`
