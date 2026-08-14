# 12 安全专项审计报告

审计日期：2026-08-13　审计员：ZCode（全区审计第 12 区，安全横切面）
审计对象：`core/src/lamtools_core/` 全量 Python 代码（154 个文件）的跨横切安全扫描，独立复核 03（HTTP）/06（tool）/09（config）之外的安全边界。
方法：全程静态只读分析（grep 定位 + 精读，无运行、无修改、无写入）。

## 1. 概况（方法/扫描面）

本区以"横切面 + 边界"为定位，在 03/06/09 三份报告之外独立复核，重点扫描六类维度：

1. **命令注入**：`subprocess`/`asyncio.create_subprocess_*` 全量调用点（mcp/client、plugins/engine、runtime/workflow、runtime/observer、tool/command_runner、tool/search/external、cli、attachment/files），无一处 `shell=True`，但发现 2 处高危面：plugin hook 的 `create_subprocess_shell` 字符串模板替换，以及 MCP/仓库配置自动拉起进程。
2. **路径穿越**：checkpoint/snapshot/mem/attachment/workflow_store/SPA 回退等所有 `open/Path/join` 入口。checkpoint 的 `_safe_workspace_path`（`checkpoint.py:1469`）、workflow 的 `_python_http_server_root` 边界校验（`command_runner.py:604-619`）均做了 `resolve()+relative_to()` 防护，未发现新穿越点（03 已记录 SPA 回退穿越与附件 session_id 越界写，不重复）。
3. **SSRF**：LLM 之外的全部 HTTP 客户端（web_tools、search/*、update/checker、plugins/engine http hook、command_runner probe）。update checker 固定 GitHub 域名；http hook 有 loopback 感知的 `trust_env` 处理；未发现用户可控 URL 的新出站点。`command_runner.py:417` 的 urllib probe 存在重定向跟随/代理环境弱项（S4）。
4. **反序列化**：无 `pickle`；`yaml` 未使用；全仓 `json.loads` 均解析本地配置文件或模型输出（信任边界内），未发现不安全反序列化。
5. **密钥与敏感信息**：发现 3 条——`settings.get` 透传 imagegen 明文 api_key、api_key 明文落盘无权限保护、provider 配置可被改写 base_url 造成密钥外带。
6. **鉴权边界**：服务器默认绑定 127.0.0.1（`cli.py:647`），但 WS/REST 全链路零鉴权（03 已记录 S1）。本区新增发现：插件 hook 信任门（`hook.trust_all`）与配置操作（`provider.update`/`settings.get`）同样无任何鉴权即暴露在 WS 上，构成独立可利用链路。

问题统计：S2×4，S3×3，S4×2，共 9 条（均为 03/06/09 未覆盖的横切面新增）。

## 2. 问题清单

### S2（高危面，利用条件受限）

- **[S2] 插件 hook 信任门可被任意本地调用方一键绕过：`hook.trust_all` 批量信任 + 仓库投递 hooks.json + command hook 的 shell 执行**
  - 位置：`plugins/operations.py:122-129`（trust_all 无任何门控）、`app/live_router.py:92-98`（WS 入口，无鉴权）、`plugins/registry.py:97-98`（项目插件目录 `hooks/hooks.json`）、`plugins/hook_config.py:44-45`（项目 `.lamtools/hooks.json`）、`plugins/engine.py:102`（`create_subprocess_shell`）。
  - 问题：hook 执行前有信任审查（`engine.py:63-65` 跳过未信任 hook，这是好的设计），但 `hook.trust`/`hook.trust_all`/`hook.untrust` 三个操作注册进 operations 目录后，经零鉴权 WS 的 `_dispatch`（`live_router.py:571-579`）可直接调用；`hook.trust_all` 一次性信任**所有** pending 状态的 hook，无需用户在场确认。恶意仓库可在 `.lamtools/hooks.json` 或插件 `hooks/hooks.json` 中投递 command 型 hook（模板含 `${PLUGIN_ROOT}` 等），攻击者网页先 `hook.trust_all`，再触发工具调用（`turn.start`），PreToolUse/PostToolUse 事件即执行 hook 声明的任意 shell 命令。
  - 影响：信任审查机制形同虚设；叠加 03 号报告已记录的零鉴权前置后，形成"网页 → 一键信任 → 任意命令执行"的完整链。即使将来修复了 03 的零鉴权，`hook.trust_all` 一键信任本身仍是单点授权缺口。
  - 修复建议：信任操作必须绑定交互式人工确认（UI 弹窗/CLI 按键），且仅允许逐个信任（去掉 trust_all 或改为逐条返回确认队列）；对来源为工作区/仓库的 hook 单独标记并默认拒绝；对 command 型 hook 增加命令模板沙箱提示（占位符必须加引号）。

- **[S2] plugin hook command 模板字符串替换 + `create_subprocess_shell`：模型可控占位符可注入 shell**
  - 位置：`plugins/engine.py:250-263`（`_expanded_command` 用 `.replace()` 把 `${TOOL_CALL_ID}`/`${TOOL_NAME}`/`${EVENT_NAME}`/`${PLUGIN_DATA}`/`${PROJECT_ROOT}` 直接拼进命令字符串）、`plugins/engine.py:102`（`asyncio.create_subprocess_shell`）。
  - 问题：`tool_call_id` 来自 LLM 输出（`kernel/loop.py:2225` `tool_call_id=call.id`），`plugin_data` 来自插件配置。hook 命令模板是用户编写的，但若模板将占位符置于 shell 语法语境（如 `echo ${TOOL_CALL_ID}` 未加引号），被 prompt 注入的模型可在 `tool_call_id` 中携带 `;`、`$(...)`、反引号、换行等元字符，经 shell 展开执行任意命令——hook 以完整用户权限运行。
  - 影响：命令注入（条件：hook 模板把占位符写在 shell 位置 + 模型输出可控，两者均现实存在）；与信任门组合后（上一条）无需用户知情即可达成。
  - 修复建议：模板展开后按 `shlex.split` 重组 argv 列表再经 `create_subprocess_exec` 执行（彻底消除 shell 语义）；或对替换值做单引号包裹/转义并校验无 `$`、`` ` ``、`;`、`&`、`|` 等字符；hook 文档明确要求占位符必须加引号。

- **[S2] 仓库/工作区投毒的 MCP 配置在无审批下自动拉起任意进程**
  - 位置：`mcp/config.py:90`（配置来源含 `{work_root}/.lamtools/mcp.json`、`{work_root}/.mcp.json`、`{work_root}/mcp.json`）、`mcp/registry.py:57-71`（`load()` 启动所有 enabled 服务器，无审批门）、`mcp/client.py:47`（`create_subprocess_exec(config.command, *config.args)`，且 `env` 由配置注入 `mcp/client.py:46`）。
  - 问题：MCP 配置的 `permission` 字段只约束**工具调用**（`mcp/registry.py:88-99`），不约束**服务器启动**。打开一个含 `.mcp.json` 的仓库/项目目录后，agent 每次构建工具箱都会自动 spawn 配置声明的任意可执行文件与参数（无 shell，但 command 可以是任意路径的二进制或 `python -c`），并以用户权限运行。
  - 影响：仓库投毒 → 打开即执行任意进程（与 06 号报告的 websearch.jsonc 投毒同族，但这是 MCP 独立面，06 未覆盖）；`env` 注入还可改写 LD_PRELOAD/PATH 等放大危害。
  - 修复建议：服务器启动前引入与 hook 信任类似的"来源 + 内容哈希"确认门；项目级（工作区内）MCP 配置仅允许白名单命令（如固定 `npx -y <pkg>` 的包名校验）或默认禁用，需用户显式启用。

- **[S2] `provider.update` 保留 api_key 可任意改 base_url → 真实密钥外带到攻击者端点**
  - 位置：`config/operations.py:120-127`（provider_update 无鉴权可调）、`config/operations.py:346-356`（`_provider_update_fields`：base_url/name/api_type 自由更新，api_key 为空或掩码时**保留旧值**）、`app/http_agent_app.py:103-126`（`CoreConfigRoutingLLMClient` 每次请求按配置解析并携带 `Authorization` 头）。
  - 问题：任何能访问 WS 的调用方（恶意网页/同机进程，03 已记录零鉴权）可 `config.providers.list` 拿到 provider id 与 `has_api_key`，再 `config.provider.update` 把 base_url 改成攻击者服务器（api_key 自动保留），最后 `turn.start` 触发一次 LLM 请求——真实 api_key 作为 Bearer 头发往攻击者端点。密钥本身从未离开配置，但"目标端点"可被改写，等价于密钥外带。
  - 影响：真实 api_key 泄露给第三方；且该缺陷不依赖零鉴权——即使将来加了 token 鉴权，任何有配置权限的客户端（如共享机器的 UI）仍可单方面改 base_url 使密钥定向外泄。
  - 修复建议：base_url 变更时必须重新输入 api_key 或以交互方式二次确认（前端弹窗 + 后端操作绑定确认状态）；将"端点路由"与"凭据"解耦（如 base_url 变更后 key 标记为需重新验证）；配置类操作与运行类操作分开授权。

### S3（加固建议）

- **[S3] `settings.get` 透传 imagegen 明文 api_key**
  - 位置：`config/operations.py:219-228`（`settings_get` 对 `core.imagegen` 命名空间原样返回 `load_imagegen_config()` 全部字段）、`config/imagegen_store.py:28-33`（配置含明文 `api_key`）。
  - 问题：`config.providers.list` 已对 api_key 做掩码（`app/http_agent_app.py:1574`），但 imagegen 设置读取未做同等处理，任何 WS 调用方（零鉴权前提下）可 `settings.get`（namespace=core.imagegen）直接读取明文 api_key。
  - 影响：密钥明文泄露给任意本地调用方；与 03 号报告的零鉴权叠加即形成可执行泄露链。
  - 修复建议：`settings_get` 返回前对 `api_key` 字段掩码并附带 `has_api_key` 标志（与 provider 列表一致）；写回时保留掩码字段不覆盖（参考 `_provider_update_fields` 的掩码语义）。

- **[S3] api_key 明文落盘且无文件权限保护**
  - 位置：`config/provider_store.py:240-246`（`write_text` 无 `chmod 0o600`，POSIX 下默认 umask 通常 0644）、`config/imagegen_store.py:37-40`（同）、`config/operations.py:245-263`（`config.import_env` 把环境变量中的 key 落盘持久化）。
  - 问题：api_key/密钥以明文 jsonc 存于配置目录，文件权限为默认值；同机其他用户/低权限进程可读配置目录直接取走密钥。Windows 下依赖用户目录 ACL，POSIX 下无任何保护。
  - 影响：同机横向读取凭据。
  - 修复建议：写入时 `os.chmod(path, 0o600)`；或迁移到系统凭据库（Windows Credential Manager / macOS Keychain / keyring）；至少对 `providers.jsonc`/`imagegen.jsonc` 写入后收紧权限并启动时校验。

- **[S3] workflow 条件表达式 `eval` 伪沙箱：受限 builtins 可逃逸**
  - 位置：`runtime/workflow.py:1693`（`eval(expr, {"__builtins__": _CONDITION_BUILTINS}, dict(bound_inputs))`）、`runtime/workflow.py:49-58`（受限 builtins 白名单）。
  - 问题：表达式由模型/用户在 workflow 编辑器中编写，虽用受限 builtins，但 eval 作用域内仍可访问对象字面量属性链：`().__class__.__bases__[0].__subclasses__()` 可枚举全部类，找到 `catch_warnings` 等类的 `__init__.__globals__` 即取得完整 `__builtins__`，进而 `__import__('os').system(...)`——沙箱形同虚设。注意条件表达式运行在 **agent 主进程内**（`workflow.py:1693`），而 command/script 节点在子进程执行（06 已记录其任意执行），逃逸后无子进程隔离兜底。
  - 影响：workflow 条件表达式逃逸 → agent 进程内任意代码执行（当前实际风险被"workflow 本身可执行任意命令"所掩盖，但伪沙箱会误导审计与防护决策）。
  - 修复建议：改为 AST 解析白名单（仅允许比较/算术/成员访问/字面量，拒绝属性访问与调用 `__` 双下划线名）；或显式声明"条件表达式为可信代码，不做沙箱承诺"，并确保 workflow 加载与运行经过权限门（同 06 的 command/script 节点建议）。

### S4（最佳实践建议）

- **[S4] 本地 HTTP 就绪探测跟随重定向且受代理环境变量影响**
  - 位置：`tool/command_runner.py:417`（`urllib.request.urlopen(probe.url, timeout=0.75)`）。
  - 问题：probe URL 固定为 `http://127.0.0.1:{port}/{uuid文件名}`（`command_runner.py:350-361`），但 `urlopen` 默认跟随重定向且读取代理环境变量；若被探测端口上运行的是攻击者控制的本地服务，可 302 重定向到外部地址，把探测 token（临时 uuid，`command_runner.py:352`）外带；代理环境变量在部分平台配置下也可能截获该请求。
  - 影响：低——token 为一次性随机值且请求后即清理，但属于可避免的信息外带通道。
  - 修复建议：使用 `urllib.request.build_opener(NoRedirectHandler)` + `ProxyHandler({})`，或改用 httpx 显式 `follow_redirects=False, trust_env=False`。

- **[S4] WebSocket 入站消息无大小/深度上限**
  - 位置：`app/live_router.py:189`（`websocket.receive_json()` 无字节数上限）、`app/live_router.py:401`（`_handle_raw` 直接 `json.loads`）。
  - 问题：WS 消息未限制体积与 JSON 深度；在零鉴权前提下（03 已记录），任意本地页面可持续发送超大/深层 JSON 消息放大内存与解析 CPU 占用，构成局域 DoS 面。
  - 影响：低——仅影响本地服务可用性。
  - 修复建议：`receive()` 后校验字节数（如 1 MiB 上限）与 JSON 深度，超限即关闭连接；对 `request_tasks` 并发数设上限。

## 3. 该区 Top 3 问题

1. **插件 hook 信任门绕过（S2，`hook.trust_all`）**：信任审查是本产品"仓库内容不可信"模型的核心防线（hook 默认跳过、需逐条信任），而 `hook.trust_all` 无鉴权、无确认、一次全信，直接瓦解该防线；叠加 03 号报告记录的零鉴权前置与 command hook 的 shell 执行，形成"任意网页 → 一键信任 → 任意命令执行"的完整利用链。这是横切面上对 03/06 报告最有增量价值的发现。
2. **plugin hook 命令模板注入 + `create_subprocess_shell`（S2）**：全仓唯一一处 `create_subprocess_shell`，且替换值含模型可控的 `tool_call_id`；命令注入面真实存在，修复方式（改 argv 列表）成本低收益高。
3. **provider 配置可改 base_url 保留密钥（S2）**：密钥不直接外泄、而是"目标端点"被改写导致密钥定向外带；该缺陷不依赖零鉴权，属于配置操作设计层面的独立缺口，也是"密钥与端点耦合"这一横切模式的典型代表。

## 4. 亮点

- **hook 信任审查设计**（`plugins/engine.py:63-65` 跳过未信任 hook；`HookTrustStore` 以内容哈希记录信任）：思路正确，本区问题仅在"信任授予"一侧的暴露面过大。
- **工具证据回传前脱敏**（`app/base_agent.py:61-66` `_MODEL_SECRET_PATTERNS` + `_redact_model_tool_evidence`）：把 `Authorization: Bearer ...`、`api_key=...`、`password=...` 等模式在送入模型前统一替换为 `[REDACTED]`，是良好的密钥泄露纵深防御。
- **路径边界处理规范**：`checkpoint.py:1469-1474`（`_safe_workspace_path` 拒绝逃逸）、`tool/command_runner.py:604-619`（`_python_http_server_root` 限定工作区）、`attachment/service.py:56-58`（`safe_filename` + `unique_path`）、`workflow.py:1516`（脚本节点 node_id 字符白名单）。
- **压缩包炸弹防护**：`tool/document_normalize.py:104-135` 对 docx/xlsx 预检条目数与解压体积上限，且只读固定内部成员（`xl/workbook.xml` 等），无 zip-slip 风险。
- **临时文件原子写**：`checkpoint.py:281-293`、`tool/spreadsheet.py:246-257` 均用 `mkstemp` + `os.replace` 原子替换，且目录限定在目标旁。
- **进程启动无 shell 为主流**：MCP、workflow command/script、observer、probe 均走 argv 列表或受控包装（`_powershell_argv` 也保持 argv 形式），仅 plugin hook 一处例外。
- **update checker 固定源**：`update/checker.py` 只查询固定 GitHub 仓库与 Release 页，无用户可控 URL。

## 5. 审计范围与方法

- **范围**：`core/src/lamtools_core/` 全部 154 个 Python 文件；重点横切面：plugins（hook/trust/registry/operations）、mcp（client/config/registry/tools）、runtime/workflow（command/script/condition 节点）、runtime/observer、config（provider/imagegen/settings 操作面）、app/live_router + live_operations（WS 操作暴露面）、checkpoint、attachment、tool/command_runner、update、mem、snapshot、kernel/tracing。
- **方法**：grep 全量定位敏感模式（`subprocess`/`shell`/`eval`/`exec`/`pickle`/`yaml`/`open`/`Path`/`httpx`/`urlopen`/`zipfile`/`mkstemp`/`api_key`/`token`/`logging`），随后对命中点逐处精读上下文，验证数据流与信任边界；与 03/06/09 报告的既有条目逐一比对去重，仅保留横切面新增问题。
- **去重说明**：零鉴权 + CORS + WS 无 Origin（03 S1）、附件上传边界与 session_id 越界写（03 S2）、SPA 回退穿越（03 S1）、web_fetch SSRF 与工作区沙箱绕过（06 S1/S2）、websearch.jsonc 投毒（06 S2）、workflow command/script 任意执行（06 S2）等已在对应报告记录，本区不重复列示；本区问题均在其之上叠加或独立于其存在。
- **局限**：纯静态分析，未运行任何代码；注入类问题的最终可利用性依赖 hook 模板/仓库内容的实际形态；`hook.trust_all` 等操作的实际暴露面受部署形态（桌面单机 vs CLI 共享）影响。
