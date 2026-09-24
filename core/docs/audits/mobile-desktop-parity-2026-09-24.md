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
| `artifact.list`、`artifact.open`、`artifact.revisions`、`artifact.restore`、`artifact.revision.restore` | 工件列表、打开、版本与回滚（生成图片等产物的版本化） | 快照里只有空的 `artifacts: {}` 字段，**无任何 artifact RPC** |
| `plugin.install`、`plugin.uninstall` | 安装/卸载插件 | 无（移动端插件表是内置静态清单） |
| `plugin.config.get`、`plugin.config.update` | 读/写插件配置（`configSchema` 驱动表单） | 无（`CoreImageGenEditor` 走通用 settings 绕过了它，但其它插件的配置面缺失） |
| `plugin.widget.get`、`plugin.widget.invoke` | 右侧栏插件挂件的读取与调用 | 只有 `plugin.widget.list` |
| `skill.create`、`skill.delete` | 新建/删除技能 | 无（只能 enable/disable） |
| `config.loadtools.get`、`config.loadtools.set` | 模式工具集配置 | 无 |
| `websearch.config.get`、`websearch.config.update` | 搜索内核配置（provider/回退/限额） | 无（Rust 搜索用内置默认值，不可配） |
| `websearch.widget.health`、`websearch.widget.snapshot` | 右侧栏搜索健康与快照 | 无 |
| `rag.docs.search`、`rag.sessions.search` | RAG 检索 | 无（桌面端在无 provider 时也报不可用） |
| `thread.outline`、`thread/read` | 会话大纲与按条目读取 | 无 |
| `command.catalog` | 命令目录 | 明确抛错"移动端独立模式尚不支持命令目录" |

### 二、功能模块层（桌面有独立子系统，移动端无对应物）

| 模块 | 桌面端 | 移动端现状 |
|---|---|---|
| 会话检查点/回滚 | `session.checkpoints.create|list|graph|restore`、`session.fork`、`session.rollback` | **完全没有**（无表、无 RPC、无 UI 数据源） |
| Goal（持久目标） | `runtime/goal.py` + `goal.*` 操作 | **完全没有** |
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

## 补充：工具层与运行时语义（CLI 维度已剔除）

移动端没有 CLI，因此"CLI 是否有移动端对应物"不作为对照项。

### 核心工具集：桌面 16 个，移动端只对上 3 个文件工具加技能/MCP/Study/搜索/生图

桌面 `core_model_tools()` 暴露 16 个：`read_file`、`list_dir`、`search_files`、`search_content`、`load_skill`、
`write_file`、`edit_file`、`run_command`、`web_fetch`、`mcp_activate`、`mcp_tool`、`sub_agent`、
`sub_agent_message`、`write_checklist`、`update_checklist`、`question`。

移动端对应情况：

| 桌面工具 | 移动端 | 影响 |
|---|---|---|
| `list_dir` / `read_file` / `write_file` | `list_files` / `read_text_file` / `write_text_file` | 有，但**名称不同** |
| `edit_file` | **已补**（0.1.14）：定点替换，要求唯一匹配，支持 `occurrence`、`before_context`/`after_context` 与 sha256 校验 |
| `search_files` / `search_content` | **已补**（0.1.14）：glob（含 `**`）与字面内容搜索，跳过 node_modules/.git/target，最多 200 条 |
| `web_fetch` | **已补**（0.1.14）：抓取并转成可读文本，`ask_user` 权限，512 KiB / 2 万字符上限 |
| `run_command` | 无（`capabilities.shell=false`） | Android 无 shell，属设计 |
| `write_checklist` / `update_checklist` | **无** | 任务清单功能整体缺失（UI 侧也看不到）|
| `question` | **无** | 没有"向用户提问"工具，只有审批流 |
| `mcp_activate` / `mcp_tool` | **语义不同**（见下） | — |
| `sub_agent` / `sub_agent_message` | 有 | ✓ |
| `load_skill` | 有（另加 `read_skill_reference`） | ✓ |

技能文本基本不依赖桌面工具名：14 个 Core 技能＋Study 技能里只有 `plugin-manager/SKILL.md` 提到一次 `edit_file`，
`search_files`/`search_content`/`web_fetch`/`run_command`/`write_checklist` 均无提及。技能数量也对上：Core 14 + Study 5。

### MCP 语义不同

桌面是**网关 + 惰性激活**：`mcp_activate` 激活某个服务器后，下一回合才拿到它的工具，另有 `mcp_tool`。
移动端 `McpToolRuntime::definitions()` 把每个服务器工具用**原名直接暴露**（`tool.function_name`），没有激活步骤。
两者都能用，但工具列表与提示词、激活语义不一致。

### Hook 类型

Rust 只支持 `command` / `http` / `prompt` 三种处理器；`command` 在移动端无法执行（无 shell），按 `skipped_unavailable`
跳过。桌面端处理器类型未逐项核对（文件位置没找对），标为未核查。

## 核查覆盖度

已完成：桌面完整方法面（164）、UI 契约与面板归位、核心工具集、MCP 语义、Hook 类型、技能数量与文本引用、
HTTP 路由、附件类型、移动端独有能力。

仍未逐项核查：① 每个面板在移动端的**实际渲染结果**（本文档只对照数据源，没有逐面板跑一遍 UI）；
② 桌面端 Hook 处理器类型的完整清单（Python 侧文件未定位到）；③ arrange 的 occurrence/signal 语义在移动端是否完整实现。
