# 03 HTTP 服务层 审计报告

审计日期：2026-08-13　审计员：ZCode（全区审计第 03 区）
审计对象：`core/src/lamtools_core/app/http_agent_app.py`、`http_agent_server.py`、`http/routes.py`、`app/factory.py`、`app/live_router.py`、`app/live_hub.py`、`app/live_operations.py`（approval 相关）、`app/default_agent.py`（turn.start/work_root 相关）、`app/operation_catalog.py`、`app/core_session_store.py`、`attachment/`（上传边界）、`config/operations.py`（settings/import_env）、`cli.py` serve 入口。
方法：全程静态只读分析（无运行、无修改）。

## 1. 概况

HTTP 服务层是一个**零鉴权**的 FastAPI 应用：`cli.py serve` 默认绑定 `127.0.0.1:5172`（`cli.py:647-648`），桌面端（Tauri）打包模式下由前端 SPA 直接调用同一套 API。服务暴露三大入口：

1. REST：`/api/core/*`（sessions/projects/files/attachments/config 等，`routes.py` + `http_agent_app.py`）；
2. WebSocket JSON-RPC：`/api/core/app-server`（`live_router.py`，承载 turn.start/approval.respond 等全部运行控制）；
3. SPA 回退路由 `/{filename:path}`（`factory.py:166-172`，frontend_dir 开启时）。

所有入口均无认证、无来源（Origin/Host）校验，CORS 配置为 `allow_origins=["*"] + allow_credentials=True`。由于不存在 cookie/session 鉴权，"凭据"概念失效，浏览器对跨域非凭据请求完全放行并允许读取响应——**任何用户访问到的恶意网页都可以静默驱动本机 agent**（含命令执行工具、文件读写、配置读取），并在 WebSocket 通道绕过人工审批（`approval_policy="auto_approve"` 直接采纳、`approval.respond` 可自问自答）。这是本区最核心的风险簇，定级 S1。

输入校验方面：项目文件 API 有 `resolve()+relative_to()` 防穿越（做得好），但上传接口存在无大小上限 + session_id 拼接存储路径的目录越界写；SPA 回退路由存在任意文件读取穿越。错误处理普遍把 `str(exc)` 直接回传给客户端并入库（内部路径/供应商响应体泄漏）。并发方面未发现明显的跨请求共享可变状态问题（事件循环单线程 + 持久化统一走 `persistence.write` 事务），REST `start_turn` 与 WS `turn.start` 并发由 durable 快照守卫兜底。

问题统计：S1×3，S2×4，S3×4，S4×4，共 15 条。

## 2. 问题清单

### S1（严重）

- **[S1] 全服务零鉴权 + CORS 全开放 + WebSocket 无 Origin 校验 —— 任意网页可远程驱动 agent 执行任意命令（RCE）**
  - 位置：`core/src/lamtools_core/app/factory.py:97-103`（CORS `allow_origins=["*"]`、`allow_credentials=True`、`allow_methods/allow_headers=["*"]`）；`core/src/lamtools_core/app/live_router.py:92-103`（WS 端点不做任何 Origin/来源校验）；`core/src/lamtools_core/http/routes.py`、`core/src/lamtools_core/app/http_agent_app.py` 全部路由无任何鉴权依赖；绑定 `core/src/lamtools_core/cli.py:647-648`（默认 127.0.0.1:5172）。
  - 问题：整个 HTTP/WS 层无 token、无 cookie、无来源检查。CORS 通配 + 凭据模式在本系统无 cookie 鉴权的场景下等于"任意来源可调用任意接口且响应可读"；WebSocket 不受 CORS 约束，任意网页可直接 `new WebSocket("ws://127.0.0.1:5172/api/core/app-server")`。
  - 影响：恶意网页可在用户浏览时：(a) 经 WS 下发 `turn.start` 让 agent 执行 bash/写文件等工具（见下一条，可免审批）；(b) 经 REST 读写项目文件、上传/下载附件、读取模型/供应商配置；(c) 经 SPA 回退路由读取任意本地文件（见 S1-3）。DNS rebinding 可进一步把攻击面扩大到局域网内其他主机。本质是本机 agent 的完全远程控制 + 数据窃取。
  - 修复建议：1) 服务端强制校验 `Origin`/`Host` 头，仅放行本机可信来源（`http://localhost:*`、`tauri://localhost`、`http://tauri.localhost` 等）；2) 启动时生成随机 token（写入桌面端配置/输出到 stdout），所有 REST 请求头与 WS 握手 query 必须携带，服务端比对；3) CORS 改为显式来源白名单而非 `*`，并移除不必要的凭据组合；4) 默认仅监听 127.0.0.1，`--host 0.0.0.0` 时强制要求启用鉴权。

- **[S1] 审批门可被任意客户端绕过：`approval_policy="auto_approve"` 直通 + `approval.respond` 自问自答**
  - 位置：`core/src/lamtools_core/app/live_operations.py:705-709`（`explicit = params.get("approval_policy")...` 直接采纳 `auto_approve`）；`core/src/lamtools_core/app/default_agent.py:411-413`（REST 路径同样放行 `auto_approve`）；`core/src/lamtools_core/http/routes.py:82-87, 300-313`（`TurnStartRequest.approval_policy` 客户端可指定）；`core/src/lamtools_core/app/live_router.py:107-146`（同一 WS 连接可对任意待批请求调用 `approval.respond`）。
  - 问题：`turn.start` 的调用方（无论 REST 还是 WS）可在 payload 中直接声明 `approval_policy: "auto_approve"`，服务端不区分调用方身份直接采纳；`approval.respond` 也没有与发起 turn 的连接绑定校验（`default_agent.py:650-760` 仅校验 request_id 与 durable 状态，不校验应答者身份）。另见 `config/operations.py:233-244`：`settings.update` 可被任意客户端把 `core.runtimeControls.permission_mode` 改为 `full_edit`，进一步把服务端默认策略也变成 auto_approve。
  - 影响：命令执行类工具（bash、文件写、skill 安装等）无需任何人工确认即可执行，配合 S1-1 构成"无人值守 RCE"。人工审批机制在 HTTP 层完全失效。
  - 修复建议：`auto_approve` 仅允许来自已鉴权且被显式授权（如 CLI 参数、桌面设置）的调用方；`approval.respond` 要求应答连接与发起 turn 的连接一致（或至少来自同一可信会话）；`settings.update` 对 `core.runtimeControls` 命名空间做服务端白名单/签名校验。

- **[S1] SPA 回退路由任意文件读取（路径穿越）**
  - 位置：`core/src/lamtools_core/app/factory.py:166-172`
  - 问题：`candidate = resolved / filename` 直接拼接用户可控的 `{filename:path}` 参数，命中即 `FileResponse` 返回；无 `resolve()` 后 containment 校验。`..` 段（或 `%2e%2e` 编码，浏览器/uvicorn 不会归一化点段）可逃逸 frontend_dir。例如 `GET /%2e%2e/%2e%2e/Users/<user>/.lam/xxx.jsonc`。响应内联返回且无 Content-Disposition，配合 CORS `*` 可被任意网页跨域读取。
  - 影响：任意本地文件读取——包括配置目录下可能含 API key 的 jsonc 文件、用户文档、系统文件；任何网页可静默窃取。
  - 修复建议：对 `filename` 做 `(resolved / filename).resolve()` 并校验 `relative_to(resolved)` 必须落在 frontend_dir 内，否则 404；或仅允许白名单文件（index.html、favicon 等），其余走 StaticFiles（其自带穿越防护）。

### S2（中等）

- **[S2] 附件上传无大小/类型边界 + session_id 目录越界写**
  - 位置：`core/src/lamtools_core/app/http_agent_app.py:620-628`（`await file.read()` 无上限）；`core/src/lamtools_core/attachment/service.py:61-67`（`target.write_bytes(content)` 整块落盘）；`core/src/lamtools_core/attachment/store.py:17-18`（`storage_root = self.data_dir / "attachments" / session_id`，session_id 来自 URL 路径未经净化）。
  - 问题：(a) 上传大小零限制，multipart 请求属于"简单请求"，任意网页可跨站触发（CORS 预检都不需要），导致内存与磁盘双耗尽（DoS）；(b) `session_id` 可含 `..`/`%2e%2e` 段（单段穿越一级），文件写到 `data_dir/attachments/..`（即 data_dir）等越界目录；文件名经 `safe_filename` 净化但目录不受控。
  - 影响：磁盘/内存 DoS；越界目录写入攻击者控制内容的文件；配合 `open` 端点（见下条）可触发本机执行。
  - 修复建议：限制上传大小（如 50MB）与并发数，流式落盘；`session_id` 白名单校验（如 `[0-9a-f-]{8,64}`）或对 storage_root 做 `resolve()+relative_to(data_dir)` 校验；对可执行/脚本类扩展名（.bat/.exe/.lnk/.html 等）限制或警告。

- **[S2] `POST /api/core/attachments/{id}/open` 可触发本机执行上传内容**
  - 位置：`core/src/lamtools_core/app/http_agent_app.py:713-718` → `core/src/lamtools_core/attachment/service.py:116-119` → `core/src/lamtools_core/attachment/files.py:80`（`open_with_default_app`）
  - 问题：无鉴权端点直接调用系统"默认程序打开"附件。攻击者可先经上传接口放入 `.bat`/`.lnk`/`.ps1`/可执行文件，再调用 `/open` 触发执行（双击等价）。上传接口返回的 attachment id 在响应体里，CORS `*` 下跨域可读，整条链可在浏览器内自动完成。
  - 影响：本机任意代码执行（等同于 S1 家族的又一入口），即使未来修复了 S1-1 的 WS 通道，该端点仍是独立 RCE 面。
  - 修复建议：移除该端点或要求显式鉴权 + 二次确认；对附件类型白名单（仅允许预览类，禁止脚本/可执行类走 open）。

- **[S2] `work_root` 等路径参数无约束，客户端可把 agent 指到任意目录（任意文件读写/目录创建）**
  - 位置：`core/src/lamtools_core/app/default_agent.py:1573-1579`（`_work_root_from_request` 直接 `Path(supplied or ...).resolve()`，无白名单）；`core/src/lamtools_core/app/http_agent_app.py:740-755`（`project.create` 接受任意 `work_root` 并 `mkdir(parents=True)` + 写初始会话）；`core/src/lamtools_core/app/http_agent_app.py:1229-1410`（subagent guide/settings 的 `work_root` 同样任意）。
  - 问题：`turn.start`/`project.create`/`config.subagent.*` 均接受客户端提供的任意绝对路径作为 work_root，不校验其位于已注册项目根之下。
  - 影响：无鉴权客户端可让 agent 在任意目录读写文件、创建目录、执行命令（work_root 决定工具工作区），等于绕过项目隔离的任意文件读写。
  - 修复建议：服务端维护已注册 work_root 白名单（`CoreProjectStore` 列表），操作前校验 `resolve()` 后必须在白名单内；或要求提供 project_id 由服务端解析路径。

- **[S2] `GET /api/core/browse-directory` 无鉴权任意目录枚举**
  - 位置：`core/src/lamtools_core/http/routes.py:586-613`
  - 问题：`browse_directory` 接受任意路径并返回目录条目（名称/类型/大小/扩展名），`_browse_root()` 还枚举所有盘符。该接口为桌面 FolderBrowserDialog 设计，但在零鉴权 + CORS 全开下成为跨域信息泄露面。
  - 影响：任意网页可枚举用户文件系统目录结构（文件名、大小、类型），为后续定向读取（配合 S1-3）提供侦察。
  - 修复建议：纳入统一鉴权；或限制只能浏览已注册项目根/数据目录；跨域来源拒绝。

### S3（轻微）

- **[S3] 异常信息直接回传客户端并入库（内部路径/供应商响应体泄漏）**
  - 位置：`core/src/lamtools_core/http/routes.py:314-325`（`detail=str(exc)` 返回 500，并把 `str(exc)` 写入会话 system 消息）；`core/src/lamtools_core/app/live_router.py:426-431, 504-507`（WS 操作异常 `message=str(exc)` 回传）；`core/src/lamtools_core/cli.py:159-163, 178-183`（LLM 上游错误体 `response.text[:300]` 进入异常消息）。
  - 问题：异常消息直接暴露内部路径、SQL/IO 细节、LLM 供应商响应体；REST 失败消息还会持久化到会话记录，长期留存。
  - 影响：信息泄漏（内部布局、供应商返回、可能含请求回显的敏感内容）；错误码/文案不一致（同一类错误有时 500 有时 422）。
  - 修复建议：对客户端仅返回通用错误文案（如 "Internal error"），详细堆栈写服务端日志；供应商响应体脱敏后入库。

- **[S3] provider 列表接口原样返回 `extra` 字段（可能含敏感配置）**
  - 位置：`core/src/lamtools_core/app/http_agent_app.py:1565-1580`（`"extra": dict(provider.extra)`）；`core/src/lamtools_core/config/operations.py:43-53`（`_provider_response` 同样原样返回 `extra`）。
  - 问题：`ProviderConfig.extra` 是自由格式字段（`provider_store.py:64`），`api_key` 做了掩码，但 `extra` 内容（可能包含 org id、二次 token、自定义密钥等）未脱敏即返回。
  - 影响：无鉴权接口可能泄露供应商配置中的敏感扩展字段。
  - 修复建议：对 `extra` 做键名/值脱敏（递归 mask 可疑 key：key/secret/token/password/credential）。

- **[S3] `settings.update` 可无约束改写运行时权限配置（纵深防御失效）**
  - 位置：`core/src/lamtools_core/config/operations.py:233-244`
  - 问题：任意客户端可把 `core.runtimeControls.permission_mode` 设为 `full_edit`、`allow_access_outside_workdir=true` 等，`_resolve_turn_approval_policy`（`live_operations.py:700-749`）会据此放行 auto_approve 与越界访问。
  - 影响：即使修复了 S1-2 的显式 auto_approve，仍可经设置通道提权；且会篡改用户本机配置文件。
  - 修复建议：`settings.update` 走统一鉴权；对安全相关命名空间（runtimeControls）做变更审计或禁止远程写入。

- **[S3] 安全响应头缺失**
  - 位置：`core/src/lamtools_core/app/factory.py:90-103`（仅 CORS，无任何安全头）
  - 问题：无 `X-Content-Type-Options`、`Content-Security-Policy`、`X-Frame-Options`、`Referrer-Policy` 等；SPA 内联返回 index.html，附件/项目文件以可猜测 content-type 内联提供。
  - 影响：配合任意文件读取/上传，存在 MIME 嗅探、点击劫持、同源注入放大面。
  - 修复建议：增加安全头中间件；对文件类响应统一 `X-Content-Type-Options: nosniff`，SPA 页配置基础 CSP。

### S4（建议）

- **[S4] `/api/health` 与配置接口泄漏内部绝对路径**
  - 位置：`core/src/lamtools_core/app/http_agent_app.py:583-591`（health 返回 `work_root`、`core_db` 绝对路径）；`:606-612`（config/models、config/providers）；`config/operations.py:948-975`（`config.resolved.get` 返回 provider `base_url`）；`http_agent_app.py:1229-1410`（subagent guide/settings 返回 `resolved_path` 完整路径）；`http_agent_app.py:907-915`（`artifact.open` 返回 `record.path`）。
  - 问题：公共接口返回服务器内部目录结构、数据库路径、供应商 base_url。
  - 影响：辅助信息收集，配合其他漏洞精确打击；无鉴权下不应暴露。
  - 修复建议：health 仅返回 status/version；内部路径仅在鉴权后按需返回。

- **[S4] `config.models.upsert` 整数/浮点转换未捕获，畸形输入导致 500**
  - 位置：`core/src/lamtools_core/app/http_agent_app.py:1116-1144`（`int(payload.get("context_window") or 0)`、`float(...)`、`int(payload.get("max_output_tokens") ...)`）
  - 问题：payload 为非数字字符串时抛 `ValueError`，经 WS `_handle_raw` 捕获后回传 `SERVER_ERROR` + 异常文本（S3 同类），REST 无此入口则 500。
  - 影响：错误处理不一致、异常文案泄漏。
  - 修复建议：用 pydantic 模型约束这些字段，或捕获转换异常返回 4xx 业务错误。

- **[S4] `PUT /projects/{id}/files/content` 请求体无模型校验（裸 dict）**
  - 位置：`core/src/lamtools_core/http/routes.py:529-554`
  - 问题：`body: dict` 无 pydantic 约束；`content` 非 str 时 `write_text` 抛 `TypeError` → 500；也无内容大小限制。
  - 影响：异常 500、超大内容写入。
  - 修复建议：定义 `{content: str}` 请求模型并限制长度。

- **[S4] REST `start_turn` 消息/请求体无长度上限（LLM 成本/内存放大）**
  - 位置：`core/src/lamtools_core/http/routes.py:82-87, 276-313`；uvicorn 侧无请求体上限（`cli.py:1207`）。
  - 问题：`message` 无最大长度限制，可提交巨量文本触发 LLM 计费与内存压力。
  - 影响：本地 DoS / 计费放大。
  - 修复建议：限制消息长度（如 200KB），并给 uvicorn 配置 `h11_max_incomplete_event_size` / 请求体上限。

## 3. 该区 Top 3 问题

1. **零鉴权 + CORS 全开 + WS 无 Origin 校验（S1）**：攻击面最大，任何网页即可完全控制本机 agent（REST + WS 双通道），是一切后续利用的根。
2. **审批门可绕过（S1）**：`auto_approve` 直通 + `approval.respond` 自答，使 agent 的命令执行工具在无人工确认下运行，把"控制"升级为"无监督 RCE"。
3. **SPA 回退路由任意文件读取（S1）**：`{filename:path}` 无 containment 校验，配合 CORS 可跨域读取任意本地文件（含配置中的 API key），是独立于 agent 通道的窃取面。

## 4. 亮点

- 项目文件类 API（`routes.py:452-554`）统一 `resolve()+relative_to(root)` 防穿越，越界返回 403，正确处理了 UnicodeDecodeError/PermissionError 等分支。
- 附件文件名经 `safe_filename` 净化 + `unique_path` 防覆盖（`attachment/files.py:14-25`），DB 写入失败时回滚删除落盘文件（`attachment/service.py:86-88`）。
- API key 输出统一 `mask_api_key` 掩码（`http_agent_app.py:1565-1580`、`config/operations.py:43-53`），代码中未发现 api_key 打日志。
- 并发模型干净：持久化统一走 `persistence.write` 事务（`core_session_store.py`），WS 事件 hub 订阅/广播无锁但均在事件循环内且迭代前快照（`live_hub.py:43-56`）；REST 与 WS 并发 turn 由 durable 快照守卫兜底（`http_agent_app.py:451-458` 注释与 `recover_stale_active_turns`）。
- 消息流健壮性处理到位：WS 出站队列满时丢消息而非断连风暴、runItem 增量 20ms 合帧、快照节流（`live_router.py:170-180, 228-239, 268-281`），大线程场景已实测优化。
- `artifact_file` 的 workspace:// 与 attachment:// 路径均落在受控解析逻辑内（`http_agent_app.py:640-678`），`resolve_artifact_id` 对绝对路径做 `relative_to` 校验（`artifact/registry.py:170-196`）。

## 5. 审计范围与方法

- 范围：`app/http_agent_app.py`（1633 行）、`app/http_agent_server.py`、`http/routes.py`（1047 行）、`app/factory.py`、`app/live_router.py`、`app/live_hub.py`、`app/live_protocol.py`、`app/live_operations.py`（审批相关段）、`app/default_agent.py`（turn.start/_work_root_from_request）、`app/operation_catalog.py`、`app/core_session_store.py`、`attachment/{service,store,files}.py`、`config/operations.py`、`cli.py`（serve 入口）及关联导入。
- 方法：全文件通读 + grep 交叉验证（鉴权/Origin/CORS/路径拼接/日志脱敏/大小限制）；严重度按"可达性 × 影响"判定，其中无鉴权假设下所有端点视为局域网/浏览器可达（默认 127.0.0.1，威胁模型为恶意网页与本地恶意进程）。
- 未覆盖：GUI 成员层、`durable_operations`/`workflow_operations` 内部实现、`llm/` 与 `tool/` 的其余部分（属其他审计区）；未运行任何代码。
