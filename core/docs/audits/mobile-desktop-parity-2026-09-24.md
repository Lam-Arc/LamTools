# 移动端 vs 桌面端 功能对照（2026-09-24）

目的：把移动端**每一个功能模块**与桌面端逐一对上，列出全部缺口，供后续逐个补齐。**只记录"有没有对上"，不评估 bug。**

## 方法

不靠记忆，机械提取三份集合后取差集：

1. **UI 契约面**：`core/ui/src` 里所有 `requestRpc('x')` / `client.request('x')` / `method: 'x'` 字面量 → **48 个方法**（这是桌面与移动共同的客户端契约）。
2. **移动端已答面**：
   - `StandaloneTransport.handleRpc` 30 个精确 + 前缀 `queue/`、`study.`、`workflow.`
   - `StandaloneConfigStore` 27、`StandaloneExtensionsStore` 16、`StandaloneArrangeStore` 10 + 前缀 `arrange.`
   - Rust 侧 Study 派发 `study.*`：15 个（`study.binding.ensure/primary`、`build`、`context`、`current`、`exam`、`get`、`layout`、`marks`、`notes`、`outbox`、`pin`、`search`、`sign`、`text`）
   - 合计 **83 个精确方法 + 4 个前缀族**
3. **桌面端已答面**：运行时枚举 `OperationCatalog.register`，`create_core_agent_http_app` 同步注册 6 个 + agent catalog 85 个 + config catalog 19 个；工厂内还有 project/artifact/session/plugin/update/mobile 等家族**在启动钩子里注册，未完整枚举**（见"方法说明"）。

## 已对齐（无需处理）

| 模块 | 桌面端 | 移动端证据 |
|---|---|---|
| 回合执行 | `turn.start` | `turn/start`、`turn/interrupt`、`turn/force_reset`、`turn/steer` |
| 审批 | `approval.respond` | `approval/respond` |
| 排队 | queue 家族 | `queue/create|update|delete|guide` |
| 会话读取/切换 | `thread/resume`、history | `thread/resume`、`thread/history` |
| 项目 | `project.list`、`project.sessions.list` | 同名方法 |
| 模型/供应商 | `config.models.*`、`config.providers.*`、`config.model*`、`config.model_group*` | 27 个 config 方法全覆盖（含 model_groups、create_with_provider、set_default） |
| 设置 | `settings.get/update` | 同名 + 命名空间处理（含 `core.imagegen`） |
| 全局指令/记忆/加载上下文 | `config.agents_md.*`、`config.memory.*`、`config.load_context.*` | 同名方法 |
| 子代理配置 | `config.subagent.guide|settings.*` | 同名方法 |
| 技能 | `skill.list|enable|disable`、`load_skill` | 同名 + Rust `skills.rs` 通用加载器 |
| Hook | `hook.list|config.get|config.update|trust|untrust|delete` | 16 个方法全覆盖 |
| 插件（基础） | `plugin.list|enable|disable|ui.list` | 同名；`widget.list` 亦有 |
| 子代理 | `sub_agent.create|close|message|list` | `sub_agent.list|snapshot|approval.respond` + Rust `sub_agent.rs` |
| Study | 14 个 `study.*` | 15 个（多 `binding.ensure/primary`），含 `marks`、`search`、`notes`、`exam`、`sign` |
| Arrange | `arrange.*` | 10 个精确 + `arrange.` 前缀 |
| 工作区搜索 | `workspace.search` | 同名 |
| 更新检查 | `update.check` | 同名 |
| 会话导出 | HTTP `POST /sessions/{id}/export` | `handleHttp` 同名路由 + `StandaloneSessionExport` |
| 附件 | HTTP `/sessions/{id}/attachments` | `handleHttp` 同名 + `attachments.rs` |
| 权限 | `session.permissions.set` + preset | 同名 |
| 记忆/Dreaming | `mem/dreaming.py` | Rust `memory.rs` + `dreaming` 载荷字段 |
| 插件工具（Agent 侧） | `git_status`、`git_diff`、`web_search`、`generate_image` | `web_search`、`generate_image` 已装配；git 已决定不做 |
| 上下文压缩 | `context-compaction` CLI + 运行时 | Rust `compaction.rs`（预算/摘要注入）|

## 缺口（逐条列出）

### 一、RPC 方法层（UI 会调用、移动端无实现 → 落到"移动端独立模式不支持"）

| 方法 | 桌面端作用 | 移动端现状 |
|---|---|---|
| `artifact.list`、`artifact.open`、`artifact.revisions`、`artifact.restore`、`artifact.revision.restore` | 工件列表、打开、版本与回滚 | **0.1.18 已对齐**：表（artifacts/artifact_revisions，blob 按 sha256 内容寻址）、操作（list/read|show/revisions/delete|remove/restore/revision.restore）、`GET /projects/{id}/artifacts/{id}/file?revision_id=` 路由、快照 `artifacts` 映射全部就位；`write_file`/`edit_file` 观察即记录版本，未变化不记新版本。**仅剩 `artifact.open`**：需要 Android intent 桥（附件面板已有同类能力），未随本版发布
| `plugin.install`、`plugin.uninstall` | 安装/卸载插件 | 无宿主：移动端没有插件加载器（Python 后端/依赖装不进 APK），插件表是内置清单。0.1.16 起该 RPC 明确抛错并在面板显示，不再假装成功 |
| `plugin.config.get`、`plugin.config.update` | 读/写插件配置（`configSchema` 驱动表单） | **已对齐**（0.1.17）：宿主内嵌 imagegen/websearch 的 `config/schema.jsonc`，`plugin.list` 因此出现配置入口（无 schema 的插件不显示入口）；写入的命名空间就是运行时读取的那个（`core.imagegen` / `core.websearch`），密钥打码/保留与桌面一致 |
| `plugin.widget.get`、`plugin.widget.invoke` | 右侧栏插件挂件的读取与调用 | 只有 `plugin.widget.list`（返回空）。移动端没有插件 UI 宿主，没有挂件可读；调用会明确抛错 |
| `skill.create`、`skill.delete` | 新建/删除技能 | **已对齐**（0.1.17）：三字段必填、名字限 `^[A-Za-z0-9._-]+$`、写 `{app_data}/skills/<name>/SKILL.md`（frontmatter 含 name/description）、已存在报错；删除只允许用户技能。该目录同时挂载进每次技能装配，新建后下一轮即可 `load_skill` |
| `config.loadtools.get`、`config.loadtools.set` | 模式工具集配置 | **已对齐**（0.1.16）：内置模式逐字一致、`source` 区分 builtin/config、`catalog` 来自 `sunday_tool_catalog`（本机真实装配）；运行时按白名单过滤并拒绝越权调用 |
| `websearch.config.get`、`websearch.config.update` | 搜索内核配置（provider/回退/限额） | **已对齐**（0.1.17）：JSONC 文档读写（注释与 URL 里的 `//` 都能过），设置真正进入 Rust 搜索——`provider` + `fallback_providers` 组成与 Python 相同的 `[provider] + fallback` 顺序，`limit`/`timeout` 生效；`proxy_port` 是桌面本地代理字段，移动端忽略 |
| `websearch.widget.health`、`websearch.widget.snapshot` | 右侧栏搜索健康与快照 | 无 |
| `rag.docs.search`、`rag.sessions.search` | RAG 检索 | 无（桌面端在无 provider 时也报不可用） |
| `thread.outline`、`thread/read` | 会话大纲与按条目读取 | 无 |
| `command.catalog` | 命令目录 | 明确抛错"移动端独立模式尚不支持命令目录" |

### 二、功能模块层（桌面有独立子系统，移动端无对应物）

| 模块 | 桌面端 | 移动端现状 |
|---|---|---|
| 会话检查点/回滚 | `session.checkpoints.*`、`session.fork`、`session.rollback` | **已对齐**（0.1.20）：节点字段/图与头/恢复载荷照桌面；检查点存项目文件清单哈希（与 artifact blob 同一内容寻址），恢复先记 undo 检查点、从 blob 写回并记新版本、删除检查点之后新建的文件；fork 派生分支会话，rollback 恢复文件并截断该回合之后的对话 |
| Goal（持久目标） | `runtime/goal.py` + `goal.*` 操作 | **已对齐**（0.1.19）：字段、状态机（active↔blocked→archived，archived 终态）、乐观并发 revision、`completed_at`、校验语与桌面一致；`goal.create/get/list/update` 齐备 |
| 定时/编排可视化 | `arrange.*` 有，`CoreArrangeManager.vue` 共享 | 有 store，但**未核实**是否覆盖 occurrence/signal 全部语义 |
| Office 文档 | `office` CLI（validate/render）+ `office-*` 技能 + 渲染合同 | 只有 `office-*` **技能文本**；无 CLI、无渲染器，技能指向的命令在移动端不可执行 |
| 命令系统 | `command.catalog`、`command.execute`、`run_command` 工具 | 无 shell 能力（`capabilities.shell=false`），无命令目录 |
| 桌面宠物 | `emotion-ball-pet` 插件 + 桌面挂件 | 按你的决定排除 |
| Workflow | 35 个 `workflow.*` + 5 个 Agent 工具 | 仅 UI RPC 面，**未向 Agent 装配工具**（按你的决定排除） |
| 移动端管控 | `mobile.*`（桌面控制已配对设备） | 手机上无对应物（方向相反，属桌面独有） |
| 远程/中继 | Gateway + Relay + 配对 | 移动端是隧道的一端（已有），无中继管理面 |

### 三、需要你确认"是否要求对应"的

1. **RAG**：桌面在无 provider 时也报不可用；移动端连"不可用"的 RPC 都没有。要不要补成"明确报不可用"？
2. **artifact（工件）**：共享 UI 的产物卡片依赖它。移动端生成图片现在落在附件里（可用），但**版本/回滚/历史**这层没有。要不要补？
3. **插件配置面**：除生图外，其它插件的 `configSchema` 表单在移动端没有读写路径。
4. **技能新建/删除**：移动端只有开关，无创建。
5. **Office 渲染**：技能存在但命令不可执行——要么补一个移动端渲染路径，要么把技能在移动端隐藏/改写。
6. **会话检查点/回滚与 Goal**：桌面是两个完整子系统，移动端为零。这是**最大的两块结构缺口**。

### 技能与 CLI 依赖（0.1.22 处理）

14 个内置技能中 7 个（office-documents/charts/slides/spreadsheets/infographics/pdf/renderer）描述了
`py -3.14 -m lamtools_core.cli office …` 的验证/渲染步骤。技能文本两平台共用、不做平台改写；
取而代之的是宿主自述能力：无 shell 的宿主在技能清单后追加一行，说明这些步骤需要桌面端、
本机应直接产出源文件、验证与渲染在桌面完成。Office 渲染本身是桌面能力（Android 无 Python
与 Office 应用），不移植。

## 补充：工具层与运行时语义（CLI 维度已剔除）

移动端没有 CLI，因此"CLI 是否有移动端对应物"不作为对照项。

### 核心工具集：桌面 16 个，移动端只对上 3 个文件工具加技能/MCP/Study/搜索/生图

桌面 `core_model_tools()` 暴露 16 个：`read_file`、`list_dir`、`search_files`、`search_content`、`load_skill`、
`write_file`、`edit_file`、`run_command`、`web_fetch`、`mcp_activate`、`mcp_tool`、`sub_agent`、
`sub_agent_message`、`write_checklist`、`update_checklist`、`question`。

移动端对应情况：

| 桌面工具 | 移动端 | 影响 |
|---|---|---|
| `list_dir` / `read_file` / `write_file` | **已对齐**（0.1.16）：移动端原名 `list_files` / `read_text_file` / `write_text_file`，因模式工具集按名匹配而必须统一 |
| `edit_file` | **已补**（0.1.14）：定点替换，要求唯一匹配，支持 `occurrence`、`before_context`/`after_context` 与 sha256 校验 |
| `search_files` / `search_content` | **已补**（0.1.14）：glob（含 `**`）与字面内容搜索，跳过 node_modules/.git/target，最多 200 条 |
| `web_fetch` | **已补**（0.1.14）：抓取并转成可读文本，`ask_user` 权限，512 KiB / 2 万字符上限 |
| `run_command` | 无（`capabilities.shell=false`） | Android 无 shell，属设计 |
| `write_checklist` / `update_checklist` | **已对齐**（0.1.21）：桌面同款 schema 与 action 集合，计划存运行时、工具结果即计划，转录按 `plan` 部件渲染 |
| `question` | **已对齐**（0.1.21）：`AlwaysAsk` 权限，任何预设下都暂停等答复 |
| `mcp_activate` / `mcp_tool` | **语义不同**（见下） | — |
| `sub_agent` / `sub_agent_message` | 有 | ✓ |
| `load_skill` | 有（另加 `read_skill_reference`） | ✓ |

工具名统一后，桌面内置模式（`loadtools.jsonc` 的 consider/execute）在移动端逐字可用：0.1.16 起
`config.loadtools.get` 返回同样的模式与描述，`sunday_tool_catalog` 只列出本机真正装配的工具，
范围之外的旧名字（`git_status` 等）不会出现在模式里。

技能文本基本不依赖桌面工具名：14 个 Core 技能＋Study 技能里只有 `plugin-manager/SKILL.md` 提到一次 `edit_file`，
`search_files`/`search_content`/`web_fetch`/`run_command`/`write_checklist` 均无提及。技能数量也对上：Core 14 + Study 5。

### MCP 语义不同

桌面是**网关 + 惰性激活**：`mcp_activate` 激活某个服务器后，下一回合才拿到它的工具，另有 `mcp_tool`。
移动端 `McpToolRuntime::definitions()` 把每个服务器工具用**原名直接暴露**（`tool.function_name`），没有激活步骤。
两者都能用，但工具列表与提示词、激活语义不一致。

### Hook 类型

Rust 只支持 `command` / `http` / `prompt` 三种处理器；`command` 在移动端无法执行（无 shell），按 `skipped_unavailable`
跳过。桌面端处理器类型未逐项核对（文件位置没找对），标为未核查。

## HTTP 路由对照

桌面路由用脚本从 `core/src/lamtools_core` 枚举 `@router`／`@app` 装饰器，共 **56 条注册**
（含 `/api/core` 前缀与 `attachment/http.py` 的重复注册）。移动端"是否处理"以
`StandaloneTransport.handleHttp` 与 `standalone/StandaloneProjectRoutes.ts` 为准；"UI 是否调用"
以扫描 `core/ui/src` 与 `core/mobile/src` 的路径字面量为准，不凭记忆。

### 一、移动端已实现（19 条，其中本批新增 7 条）

| 路由 | 移动端实现 |
|---|---|
| `GET|POST /sessions` | `handleHttp` + 本地库 |
| `PATCH|DELETE /sessions/{id}` | 同上 |
| `POST /sessions/{id}/export` | `StandaloneSessionExport` |
| `GET|POST /sessions/{id}/attachments` | `handleHttp` + `attachments.rs` |
| `GET|DELETE /attachments/{id}`、`/download`、`/preview`、`POST /open` | 同上 |
| `GET /browse-directory` | **本批新增**：复用 project client 的 `browseDirectory`，与桌面一样隐藏点文件与构建目录 |
| `GET|PUT /projects/{id}/agents-md` | **本批新增**：Rust `project_agents_md`，读写的就是 Agent 上下文加载的同一个文件 |
| `GET /projects/{id}/files` | **本批新增**：复用 client `listFiles`，隐藏 node_modules/.git/dist 等目录 |
| `GET|PUT /projects/{id}/files/content` | **本批新增**：PUT 要求文件已存在，与桌面一致（桌面不通过此路由建文件） |
| `GET /projects/{id}/files/raw` | **本批新增**：Rust `project_file_read_raw` 返回真实字节与 MIME，消息/舞台的图片、视频、PDF 预览由 403 变为可用 |

### 二、UI 走 project client，不走路由（7 条，行为已对齐）

`GET|POST /projects`、`GET|PATCH|DELETE /projects/{id}`、`GET|POST /projects/{id}/sessions`。
移动端本地模式用 `createStandaloneProjectClient`（Rust 命令直连），远端模式用真实桌面 HTTP，
两条路径都不经过 `handleHttp`，所以路由缺失不影响面板。

### 三、UI 从不调用，仅桌面服务端/CLI/隧道消费者（12 条）

`GET /sessions/{id}`、`GET|POST /sessions/{id}/messages`、`GET|POST /sessions/{id}/events`、
`POST /sessions/{id}/turns`、`GET /sessions/{id}/export/capabilities`、
`POST /threads/{id}/export`、`GET /threads/{id}/export/capabilities`、
`GET|POST /providers`、`GET /providers/default`、`GET|POST /usage`、`GET /usage/total`。

扫描证据（`core/ui/src` + `core/mobile/src` 路径字面量命中数）：`/providers` 0、`/usage` 0、
`/threads` 0、`/messages` 0、`/events` 0、`/turns` 0、`export/capabilities` 0。

### 四、桌面专属（移动端不适用）

`GET /`、`GET /{filename:path}`（静态资源）、`GET /api/health`、`GET /api/members`（已归档 member）、
`GET /api/core/desktop-plugins*`（桌宠/桌面插件）、`GET /api/core/config/models|providers`（桌面配置文件直读）。

### 五、未对齐且 UI 会调用（1 条，归批次 4）

`GET /projects/{id}/artifacts/{artifact_id}/file`：消息与舞台的成果预览直接请求该路由
（`LamToolsApp.vue:1503`、`MessageView.vue:2445`、`MessageAttachmentDeck.vue:610`），移动端目前 403，
需要批次 4 的 artifact 存储落地后才能实现。

## 状态归属：切会话丢过程（0.1.23 修复）

原故障：运行中回合的实时状态只在传输层内存快照里，写库有去抖，`thread/resume` 从库里答，于是切走再切回看到的是「比刚离开时更空」的会话（只剩请求头动画）。

修复：`snapshotFor` 先看活快照；该线程存在 running/waiting 回合时，这个对象就是状态的所有者（与桌面「服务器持有运行中回合、resume 从它回答」同形），只把新读到的会话元数据合并上去。没有在跑回合的线程仍走库。回归测试覆盖原路径。

## 行为审计补充（8 条，0.1.24–0.1.28 修复）

上面各节对照的是「移动端有没有这个能力」——方法面、路由、工具清单、面板数据源。它看不见**已存在代码内部**的行为缺陷：常量、线上形状、错误与取消路径、竞态、失效注释。真机按严重度报出 8 条，全部落在这一层。

### P1-1 应用内「检查更新」必然失败（0.1.26）

- 根因：客户端固定请求 `https://47.114.43.99.nip.io/downloads/mobile-update.json`（`StandaloneUpdate.ts`），而该文件从未上线——发版流程只 bump 本地 `core/mobile/update-manifest.json`，`deploy.py`、`site_deploy.py`、`verify_public.py` 都不生成、不上传、不校验它，连续 10 个版本如此。2026-09-24 的服务器预检仍打印 `no update manifest published`。
- 修复：0.1.24 起把清单作为发布步骤——内容由**构建出的 APK 元数据**生成（`aapt` 读回 versionName），与仓库副本比对（不一致即中止），随 APK 用同一把受限密钥上传并原子安装；`verify_public.py` 断言清单 200、版本等于本次发布、字节哈希一致、`download_url` 200 且长度等于本次 APK。0.1.26 补齐客户端：所有失败自述地址（HTTP 状态、不可达/超时、非 JSON、三项内容校验），非对象 body 不再以 `TypeError` 形式出现。
- 证据：`core/mobile/artifacts/release-1024/RELEASE.md`（首次上线）、`release-1026/RELEASE.md`（客户端）。发布后用**线上函数**跑真实地址：已装 0.1.26 → `up_to_date`，已装 0.1.0 → `update_available`（latest 0.1.26 + APK 地址）。
- 残留：地址是编译期常量，换域名需重新发版。

### P1-2 工具轮次硬上限把整轮判为失败（0.1.24）

- 根因：`runtime-rs/src/lib.rs` 的 `MAX_TOOL_ROUNDS = 8` 与 `RuntimeError::ToolLimit`——第 9 轮工具调用直接 `return Err`，连同 `TurnContinuation` 一起丢弃：8 轮工具结果、第 9 轮模型输出、`runtime_history` 全部蒸发。桌面 Python kernel 无此上限（`kernel/loop.py` 明说不设步数预算）。
- 修复：删掉常量与错误变体；按桌面语义实现两道基于证据的闸门——纯工具轮计数（桌面 `max_tool_only_rounds_without_progress`，默认 8，达阈值后每轮注入桌面原文 `[TOOL_PROGRESS_REQUIRED]`，模型说话即归零），以及重复结果停止（桌面 `max_identical_tool_results` 10/窗口 12，指纹 = 工具名 + 精确参数 + 精确结果的 SHA-256）。桌面在重复处**暂停等用户**，移动端没有暂停面，改为**可恢复收尾**：不报错、不丢消息、原因进 `runtime_warnings`（transcript 已有展示路径），并给模型一次不带工具的收尾请求。两个阈值都可由 `TurnOptions` 调整（缺省 = 桌面默认，0 = 关闭）。
- 证据：runtime-rs 146 项（新增 4 项：12 连纯工具轮全部执行且历史完整、闸门正好落在第 8–12 轮且被叙述轮归零、重复 10 次后停止且 10 轮完整 + 1 条告警 + 最后一次请求无工具、阈值默认与关闭）；注入文案与 `kernel/loop.py` 字面量逐字节一致。
- 残留：桌面还有一层「进度回复不完整则再要求」的校验（`TOOL_PROGRESS_INCOMPLETE`）未移植；重复停止按「轮末窗口计数」评估，与桌面「逐结果即停」在极端混合批次上略有差异。

### P2-3 取消 / 失败一次后整条会话上下文退化为纯文本（0.1.25）

- 根因：`conversationMessages` 只在「最近一个已结束回合是 completed 且正是它写的库」时才用持久化的 `rust_runtime_history`，否则回退到只认 `userMessage`/`agentMessage` 的 item 投影——工具调用与结果静默丢弃；而 `persistRuntimeState` 只在成功路径调用，于是一次取消或失败就抹掉整条会话的工具上下文。
- 修复：门槛改为「写它的那个回合仍是本会话的 completed 回合」；该回合之后各回合的消息（用户内容与**已完成**的回答）按 seq 顺序补上。持久化历史写在源回合结束时、不可能包含更晚回合，所以不会重复；竞态测试（取消回合在写库途中落盘）保持原期望。
- 证据：两轮会话断言完整数组；对旧实现 stash 后重跑，两个新测试分别给出 5 条（缺工具步）与 5 条（含错误文案）而失败。

### P2-4 附件走 JSON 数字数组、历史图片每轮重读（0.1.27）

- 根因：`sunday_attachment_save/read` 的 `bytes: Vec<u8>` 走 JSON 数字数组（50 MiB → 150+ MB 文本），TS 侧再 `Array.from`/`Uint8Array.from` 转一遍；`hydrateImageMessages` 在每个回合、每次审批续传都重读历史里**所有**图片（`nativeAttachments.read` + base64），无缓存。
- 修复：两条命令改 `dataBase64`（与 `sunday_artifact_file`、`project_file_read_raw` 同形；命令面上已无 `Vec<u8>`），客户端对外签名保持 `Uint8Array`（调用方零改动），50 MiB 限制改为按解码后长度判断；附件正文按 id 有界缓存（32 MiB，最旧淘汰，`delete` 与再次 `save` 都正确失效）。
- 证据：上传后下载不再读盘、两轮之间同一图片只读一次两条测试；三处钉旧协议的断言随线上形状更新。
- 残留：未引入 `tauri::ipc::Response` 裸字节通道（base64 是本仓既有形状，50 MiB 最坏情形从约 4 倍降到约 1.33 倍）。

### P3-5 Workflow 模式入口被失效注释挡住（0.1.28）

- 根因：`StandaloneExtensionsStore.ts` 注释写「native host has no Workflow RPC/backend yet」，而 RPC 与 Rust 后端早已存在。
- 处理（按你的决定：继续隐藏）：注释改为如实描述——已实现 list/list_grouped/create/get/document.get/save/compile/semantic/import.comfyui/export.comfyui/run/cancel/rename/expose/unexpose/object_info/activation.list/queue.*/human_task.list/delete；缺 `workflow.tools.list`，`activate`/`deactivate` 需 Arrange 调度器，`human_task.get|complete|timeout`/`signal` 需完整执行后端，`pause`/`resume` 需可暂停 runner。入口保持关闭，`standalone-extensions.test.ts` 的「workflow 模式不出现」断言不变。

### P3-6 失败轮次的错误文案作为 assistant 消息回灌（0.1.25）

- 根因：同一处投影只跳过 `cancelled`、不跳过 `failed`，于是上一轮错误文案（如 `工具调用轮次已达上限`）被当成模型说过的话喂回下一轮。
- 修复：投影同时跳过 failed，且**只**影响模型历史——用户仍看得到失败（测试断言快照里 failed item 仍在）。

### P3-7 空闲时 `queue/create` 返回另一个方法的形状（0.1.28）

- 根因：没有活跃回合时 `queue/create` 直接 `return await this.startTurn(params)`，返回 `turn/start` 的 `{accepted, turn_id, revision}`，而共享 UI 的 `queueInput` 按 queue 响应处理（桌面 `queue/create` 永远入队并返回 `{queue_item, events, snapshot}`）。
- 修复：一律先入队，空闲时立即 `dispatchQueued`（移动端没有空闲派发器，留在队列里的消息看起来像发送丢失），返回本方法的 `{snapshot, queue_item_id}` 信封；派发失败仍由 `dispatchQueued` 把消息放回队列。
- 证据：新测试断言应答无 `accepted`、有 `queue_item_id`，返回时消息已作为回合发出且队列已空；对旧实现该测试失败（`expected true to be undefined`）。`turn/steer` 在无活跃回合时拒绝的测试在新旧实现下都通过（守卫本就存在），保留为契约覆盖。

### P3-8 `openStudySession` 先查后建且无锁（0.1.28）

- 根因：查（`listSessions`）→ 建（`createLocalSession`）之间隔着 await，两次点同一个节点会各建一个会话，调用方拿到其中一个，另一个成为孤儿。
- 修复：按 `${kind}:${subjectId}` 在途去重（覆盖 `study.get` 的 await），完成后释放；节点校验前置到去重之前，语义与错误文案不变。
- 证据：`Promise.all` 并发两次 `study.session`，断言只建一个会话且两个 `session_id` 相同；对旧实现该测试给出两个不同 id 而失败。

### 结论：为什么「能力对齐」没看出这 8 条

对齐核查的输入是**面**（方法是否存在、路由是否注册、工具是否在清单里），输出是「移动端有没有」。这 8 条全部发生在**已经存在**的代码内部：一个常量、一个线上形状、一个失败分支、一次 await 间的竞态、一条没跟着实现走的注释。面核查发现不了它们，而当时的验证也只到「测试全绿 + 包能装」，没有真机跑一条会触发这些路径的任务。后续同类审计应把「行为契约」（阈值 / 形状 / 错误与取消路径 / 并发）作为独立一层，并要求每条都有能对着旧实现失败的回归测试。

## 补充：连接类失败重试预算不对齐（0.1.29 修复）

上一节写完「把行为契约独立成层」之后，真机日志（2026-09-24 15:01 那次 5.7 秒失败的回合）又暴露出这一层里的第一条漏项，且**不是**用户报的 8 条之一。

- 现象：模型请求在拿到响应头之前连接失败，两次就放弃，整轮判失败（15:01:10.665 首次、15:01:11.084 重试、15:01:16.318 放弃）；而 45 秒前（15:00:25）同类错误重试一次就成功。桌面在同一份 `model_retry.jsonc`、同样的默认值下会重试到 10 次（约 34 秒等待窗口 + 每次耗时）。
- 根因：`runtime-rs` 把「响应头之前」的失败单独归为 `AttemptOutcome::RetryConnection` 并把预算硬夹成 `attempts.min(2)`；桌面 `llm/retry.py` 里这类错误只是普通 `retryable`，吃满配置的尝试次数。除这一处外，两侧的重试参数完全同值（10 次 / `[1,1,2,5,5]` / jitter / 360 s / 120 s 空闲）。
- 修复：删掉夹取与 `RetryConnection` 变体，响应头前的失败与其它瞬时失败同预算；类别仍由阶段名 `http_connect_error` / `http_send_timeout` 表达。测试从「只允许两次」改为「跑满配置的十次」，并新增一条「配置三次就发三次」。
- 证据：把夹取临时还原后，两条新测试分别以 `left: 2, right: 10` 与 `left: 2, right: 3` 失败。
- 行为变化：真断网时一轮会在约 34 秒后才失败（此前约 6 秒），期间 UI 一直显示「等待重试模型请求」，随时可取消。

### 为什么这条没在上一轮行为审计里查出来

这一节的用途是让下一次别再漏，逐条原因如下。

1. **审计清单是按「面」枚举的，从来没有一份「策略数值清单」。** 上一轮对照的是方法/路由/工具/面板；重试预算既不在用户报的 8 条里，也不在任何清单上。修别的缺陷时我读过 `provider.rs` 多次，读的是工具与流式路径，没读「哪种错误拿多少次预算」这张决策表。
2. **默认值一致，所以「比默认值」这条捷径会得出「已对齐」。** Rust 侧 `RetryPolicy::default()` 是照桌面抄的（10 次 / 1,1,2,5,5 / jitter / 360 s / 120 s），差异藏在**调用点的夹取**里。只有把两侧的「错误分类 → 预算」逐类列出才看得见：桌面 4 类错误共用 1 个预算，移动端 3 类共用 2 个。
3. **有一条测试把这个差异写成了预期行为，而我把「测试通过」当成了正确性证据。** 旧测试名与被断言的句子就是 `preheader failures get only two attempts`。审计时我的检查是「移动端有没有 X、有没有测试」；一条断言本身就是差异的测试，读起来像特性。正确做法（后来在 `MAX_TOOL_ROUNDS` 上用到的）是：**见到任何守卫/阈值/上限，先问「桌面在这里是多少」，再问「这条测试凭什么这么断言」**。
4. **这一类的历史证据被错误归因，之后就被关掉了。** 响应头前失败最早按 Android TLS/证书问题排查（日记里也留有「响应头前连接失败」的记录），那类问题修好之后，日志里再出现同类失败就默认归入「网络问题」，不再当成策略问题看。
5. **日志无法自证。** `http_*` 阶段在诊断白名单里，但阶段名不带尝试序号或上限——包含这个 bug 的日志证明不了「2 次是策略上限还是偶然」。所以对齐（0.1.29）与「让日志自证」是两件事：**建议**在预算用尽时补一个阶段（如 `http_attempts_exhausted`），下次日志直接写明「重试 N 次后放弃」，不必人工比对代码。

### 下一步的检查表：把策略数值当成独立一层

- 已核对并已对齐：重试次数 / 间隔 / 抖动 / 单次超时 / 流式空闲超时（本节）；纯工具轮阈值、重复结果阈值与窗口（0.1.24）；HTTP 路由与工具命名（0.1.15/0.1.16）。
- 已核对但**有意不一致**（需保留或另行决定）：响应头期限 120 s —— 移动端对「连上但一直不给头」有 120 秒上限，桌面流式调用在连接阶段没有墙钟上限（空闲检测只在事件到达后生效），即桌面会把这类失败交给操作系统（分钟级）。这一条不盲目对齐，理由与现状写在 `release-1029/RELEASE.md`。
- **尚未核对**（下一轮要逐项列值对照）：上下文压缩阈值 / 保留步数 / 摘要输出预留；图片尺寸与总预算（每张、每条消息、张数）；`web_search` 返回条数与超时；历史行数上限；子代理步数或预算；并发工具数；MCP 超时；日志/预览类截断长度（如 `MAX_TOOL_STREAM_CHARS`）。

## 核查覆盖度

已完成：桌面完整方法面（164）、UI 契约与面板归位、核心工具集、MCP 语义、Hook 类型、技能数量与文本引用、
HTTP 路由（见上节逐条对照）、附件类型、移动端独有能力。

仍未逐项核查：① 每个面板在移动端的**实际渲染结果**（本文档只对照数据源，没有逐面板跑一遍 UI）；
② 桌面端 Hook 处理器类型的完整清单（Python 侧文件未定位到）；③ arrange 的 occurrence/signal 语义在移动端是否完整实现。
