# CLI 与 GUI 功能入口审查（2026-06-29）

本审查只以当前源码为准，不沿用旧文档结论。口径如下：

- **内部接口**：没有用户可直接点击或直接输入的 CLI/GUI 入口，只被成员后端、前端适配层、桌面外壳、测试或开发脚本调用。
- **外部操作接口**：用户能通过 CLI 命令或 GUI 操作触达的入口。
- **Core 指令**：仓库级维护命令、Core UI demo、Core 兼容 HTTP 面；不包含 Writer/Artist 业务动作。
- **Member 指令**：`writer`、`artist` 及对应产品 GUI。

主要源码依据：`writer.cmd`、`artist.cmd`、`scripts/member_cli.py`、`scripts/*.ps1`、`core/src/lamtools_core/**`、`core/ui/**`、`members/writer/backend/**`、`members/writer/frontend/src/**`、`members/artist/backend/**`、`members/artist/frontend/src/**`。

## 第一步：功能分类

### Core

#### 内部接口

| 功能区 | 接口位置 | 调用时机 |
|---|---|---|
| 应用工厂与成员注册 | `core/src/lamtools_core/app/factory.py` | Writer/Artist 后端启动时创建 FastAPI、注册成员 manifest、挂健康检查和成员列表。 |
| Core HTTP 路由工厂 | `core/src/lamtools_core/http/routes.py` | 仅在成员显式挂载 `/api/core` 或 `enable_core_routes=True` 时可用；当前 Writer/Artist 都用成员适配器挂载。 |
| Core runtime/kernel/kit 协议 | `core/src/lamtools_core/kernel/**` 等 | 成员运行 Agent 任务时调用；用户不直接调用。 |
| Core UI 组件库 | `core/ui/src/components/**`、`core/ui/src/composables/**` | Writer/Artist 前端复用 WorkspaceShell、SessionSidebar、ChatThread、RuntimePanel。 |
| Core UI controller | `useCoreWorkbenchController` | 成员前端把产品接口适配成统一工作台接口时调用。 |

#### 外部操作接口

| 分类 | 功能 | CLI 调用 | GUI 调用方式 |
|---|---|---|---|
| CLI 且 GUI | Core UI demo | `.\scripts\dev.ps1 core frontend` | 打开 `http://127.0.0.1:5173`，仅为组件 demo，不是产品工作台。 |
| 仅 CLI | Core build | `.\scripts\build.ps1 core` | 无 |
| 仅 CLI | Core test | `.\scripts\test.ps1 core` | 无 |
| 仅 CLI | 新成员脚手架 | `.\scripts\scaffold-member.ps1 -Id <id> -Name <name> [-DisplayName <name>] [-Capabilities code,git] [-DryRun]` | 无 |
| 仅 GUI | 无 | 无 | 当前没有 Core 产品级 GUI。 |

### Writer Member

#### 内部接口

| 功能区 | 接口位置 | 调用时机 |
|---|---|---|
| Writer REST 产品面 | `/api/sessions`、`/api/projects`、`/api/config`、`/api/attachments` | GUI store、后端服务调用。`/messages` 是持久化消息接口，不等同于启动一次 Writer 任务。维护标注（2026-07-01）：旧 `/api/sessions/{id}/runtime-events` 查询入口已删除，runtime event 仅作为内部过渡投影事实保留。 |
| Writer Core 兼容面 | `/api/core/sessions`、`/api/core/sessions/{id}/messages`、`/api/core/sessions/{id}/events`、`/api/core/providers`、`/api/core/usage` | Workbench 统一 controller 读取会话、消息、事件、provider；属于 Core 形状的成员适配层。 |
| Writer app-server 协议 | `/api/app-server-token`、WebSocket `/api/app-server` | CLI 与 GUI 的主运行链路；方法包括 `thread/start`、`thread/resume`、`turn/start`、`turn/steer`、`turn/interrupt`、`queue/create/update/delete`、`approval/respond`、`artifact/read/open`。 |
| Novel 路由 | `/api/writer/novel/**` | 当前主 CLI/GUI 未直接暴露，属于产品子能力或遗留/预留 HTTP 能力。 |
| Attachment 路由 | `/api/sessions/{id}/attachments`、`/api/attachments/{id}` | API wrapper 存在，但当前 Workbench 没有明显上传/预览入口；应先标为预留能力。 |
| Debug 持久化 | `/debug/decision-point`、`/debug/step` | 维护标注（2026-06-30）：已删除后端 endpoint 与 CLI debug/message/step 注入命令。 |

#### 外部操作接口

| 分类 | 功能 | CLI 调用 | GUI 调用方式 |
|---|---|---|---|
| CLI 且 GUI | 启动任务 | `writer run <task...> [--work-root <path>] [--model-id <id>]` | Writer 主界面 `/`，输入任务并发送。 |
| CLI 且 GUI | 继续会话 | `writer resume <session-id> <message...>`；维护标注（2026-06-30）：旧 `writer chat` 已删除 | 选中会话后在输入框发送；运行中会进入队列/引导逻辑。 |
| CLI 且 GUI | 查看会话 | `writer session list`、`writer session messages <id>`、`writer session status <id>`、`writer session result <id>` | 左侧会话列表、主消息流、右侧运行状态。 |
| CLI 且 GUI | 新建会话 | `writer session new [title]` | 左侧新会话按钮；新建项目后也会创建会话。 |
| CLI 且 GUI | 停止任务 | `writer cancel <session-id>` | 输入框发送按钮在运行且无文本时变为 stop。 |
| CLI 且 GUI | 用户决策 | `writer run ... --interactive-decisions` | 对话流里的决策卡片。 |
| 仅 CLI | 健康检查 | `writer health` | 无直接按钮；GUI 启动时隐式依赖后端健康。 |
| 仅 CLI | 观察运行流 | `writer watch <session-id> [--raw] [--verbose]` | GUI 通过选择会话查看实时/历史状态，不提供 watch 命令形态。 |
| 仅 CLI | 快速单次 | 维护标注（2026-06-30）：旧 `writer quick` 已删除，使用 `writer run` | GUI 没有独立 quick 模式；普通发送已覆盖。 |
| 仅 CLI | 直接 Agent | 维护标注（2026-06-30）：旧 `writer agent ...` 已删除 | GUI 只配置 Agent/子 Agent，不提供直接运行指定 Agent 的入口。 |
| 仅 CLI | 直接工具 | 维护标注（2026-06-30）：旧 `writer tool ...` 已删除 | 无普通 GUI 入口。 |
| 仅 CLI | Debug 注入 | 维护标注（2026-06-30）：旧 debug/message/step 注入入口已删除 | 无普通 GUI 入口。 |
| 仅 GUI | 项目管理 | 无 | 主界面左侧：新建项目、删除项目、按项目分组会话。 |
| 仅 GUI | `AGENTS.md` 编辑 | 无 | 项目上下文菜单打开 `AGENTS.md` 弹窗并保存。 |
| 仅 GUI | 模型/API 配置 | 无 | `/settings` → “模型与 API”：Provider/Model 增删改、从环境导入。 |
| 仅 GUI | 模型路由与运行策略 | 无 | `/settings` → “工具与 Agent”：主模型/子 Agent 模型、工具开关、命令权限策略。 |
| 仅 GUI | 项目子 Agent 定义 | 无 | `/settings` → “工具与 Agent”：新增/保存/删除项目 Agent。 |
| 仅 GUI | 代码改动审查 | 无 | 右侧“改动审查”：刷新、查看 diff、撤销全部/单文件。 |
| 仅 GUI | Commit 验收 | 无 | 右侧“请验收”：通过并提交、需要调整、稍后。 |
| 仅 GUI | Agent 分支处理 | 无 | 右侧“隔离结果”：查看、合并、放弃。 |
| 仅 GUI | 检查点 | 无 | 右侧“检查点”：保存、回退。 |
| 仅 GUI | 主题/UI 设置 | 无 | `/settings` → “界面”。 |

### Artist Member

#### 内部接口

| 功能区 | 接口位置 | 调用时机 |
|---|---|---|
| Artist 产品会话面 | `/api/sessions/**` | GUI 工作台、CLI 运行、后端服务调用；当前主任务入口是 `/artist-turn`。 |
| Artist Core 兼容面 | `/api/core/sessions`、`/api/core/sessions/{id}/messages`、`/api/core/sessions/{id}/events`、`/api/core/providers`、`/api/core/usage/total` | GUI 工作台通过 Core controller 读取会话/消息/事件；发送时转到产品动作 `/artist-turn`。 |
| Provider/Vendor 配置 | `/api/vendors/**`、`/api/providers/**` | Settings 的 API 管理使用。 |
| Settings/下载 | `/api/settings/**`、`/api/download/**` | Settings 使用默认模型、下载目录；下载 API 当前没有主界面显式下载按钮。 |
| Billing/Reference/Dashboard | `/api/billing/**`、`/api/references/**`、`/api/dashboard/stats` | 后端和部分 store/API 存在，但当前主路由没有完整页面入口。 |
| Lineage/Long-task | `/api/sessions/{id}/lineage-*`、`/api/sessions/{id}/long-task*` | API wrapper/组件存在，当前主 Workbench 没有完整可见入口。 |
| Desktop pywebview 外壳 | `members/artist/desktop/**` | 打包或桌面运行时启动本地后端和窗口。 |

#### 外部操作接口

| 分类 | 功能 | CLI 调用 | GUI 调用方式 |
|---|---|---|---|
| CLI 且 GUI | 运行生图/Agent 任务 | `artist run <prompt...>` | Artist 主界面 `/`，输入生图指令并发送。 |
| CLI 且 GUI | 继续会话 | `artist resume <session-id> <prompt...>` 或 `artist session <session-id> <prompt...>` | 选中会话后输入继续指令。 |
| CLI 且 GUI | 新建/列出会话 | `artist session new`、`artist session list` | 左侧会话区新建/选择。 |
| 仅 CLI | 直接图片生成 | `artist image <prompt...> [--image-count n] [--image-size 1024x1024]` | GUI 没有单独的 direct image 命令；主输入统一走 Artist turn。 |
| CLI 且 GUI | 会话复制/重命名 | `artist session copy <uuid>`、`artist session rename <uuid> <title>` | 左侧会话区支持重命名；复制仍以 CLI 为主。 |
| 仅 CLI | Mock/临时 provider 覆盖 | `--mock image|all`、`--image-provider-id`、`--vlm-provider-id` 等 | GUI 没有同等临时运行参数。 |
| 仅 CLI | 健康检查 | `artist health` | 无直接按钮。 |
| 仅 GUI | 会话分组 | 无 | 主界面左侧“新建分组”、删除分组；分组保存在 localStorage。 |
| 仅 GUI | Provider/模型配置 | 无可靠 CLI | `/settings` → API 管理：供应商、模型、测试连接。 |
| 仅 GUI | 默认模型与生成参数 | 无 | `/settings` → 模型默认值、生成参数。 |
| 仅 GUI | 下载目录 | 无 | `/settings` → 下载设置。 |
| 仅 GUI | 清除前端缓存 | 无 | `/settings` → 清除缓存；当前只清 localStorage。 |
| 仅 GUI | 主题/UI 设置 | 无 | `/settings` → 界面。 |

## 第二步：调用与接口合理性分析

### 命名统一性

1. **Core 与 member 的命名边界基本正确，但根命令不完整。** `scripts/dev.ps1|build.ps1|test.ps1` 以 `core/writer/artist/all` 为第一参数，符合 monorepo 边界；但没有统一的 `lamtools` 根命令，维护脚本和产品命令还是两套入口。
2. **Writer 有两套会话命令形态。** 根入口推荐 `writer session list/new/messages/status/result`，底层原生命令是 `writer list/new/messages/status/result`。功能重复，初学者需要记两套。
3. **Writer 的运行动词偏多。** 维护标注（2026-06-30）：旧 `quick/chat/message send` 已删除；当前普通 CLI 任务入口只保留 `run/resume/watch/cancel`。
4. **Writer 协议命名混用 `session` 与 `thread`。** REST、GUI store、CLI 对用户叫 `session_id`，app-server 内部叫 `thread_id`。内部可以保留，但外部文档必须统一叫“会话”。
5. **Artist CLI 是位置参数式，不是子命令式。** `artist session --help` 不能给出真正的 session 子命令帮助；`ct <goal>` 出现在 help 文案里，但当前实现没有独立 `ct` 分支。
6. **Artist 与 Writer 的 provider/model 命名不统一。** Writer 是 `Provider + Model`；Artist 是 `Vendor + Provider/Model` 混合。用户层面建议统一为“供应商 + 模型”。
7. **Artist 有 `/generate` 与 `/artist-turn` 双入口。** 当前 GUI 使用 `/artist-turn`；`/generate` 应标为 legacy 或收敛，否则会误导调用方。

### 完备性

1. **已发现并修复 Artist 根 CLI 分发错误。** 原先 `scripts/member_cli.py` 调用不存在的 `members/artist/backend/artist.py`；实际入口是 `app.cli`。
2. **Writer CLI 缺少 GUI 已有的管理能力。** 例如项目管理、Provider/Model 管理、模型路由、项目 Agent、检查点、commit 验收、Agent 分支处理、撤销改动、会话删除。
3. **Artist CLI 缺少 GUI 已有的设置能力。** 例如 Provider/模型 CRUD、默认模型、下载目录、数据导入、主题设置。
4. **部分后端能力没有 GUI 或 CLI。** Writer attachment/novel，Artist reference/billing detail/dashboard/long-task/lineage 都属于已存在但未形成稳定用户入口的能力。
5. **Sidebar 重命名存在可见控件但父组件未接线。** `SessionSidebar` 会发 `rename-session`，当前 Writer/Artist Workbench 模板没有绑定处理；对用户来说这是“看似可改、实际不可持久”的入口缺口。
6. **脚手架不是完整注册接口。** `scaffold-member.ps1` 会生成成员目录和根 `.cmd`，但不会自动把新成员接入 `scripts/dev.ps1`、`build.ps1`、`test.ps1`，也没有完整更新 root 路由配置的闭环。

### 简化与复用建议

1. **外部只保留一个主运行接口。** Writer 对用户主推 `writer run`、`writer resume`、`writer watch`、`writer cancel`；维护标注（2026-06-30）：`quick/chat` 已删除。GUI 主推同一套“发送/继续/停止/决策”语义。
2. **把“写消息”和“启动任务”明确拆开。** Core `/messages`、Writer `/messages`、Artist `/messages` 只表示持久化消息；真正任务触发分别是 Writer app-server `turn/start` 和 Artist `/artist-turn`。
3. **补齐 session 生命周期一致性。** 两个成员都应有 `session list/new/delete/rename/messages/status` 的 CLI/GUI 对应关系；没有实现的要么补，要么从 GUI 隐藏控件。
4. **Provider/Model 统一术语。** 用户文档统一叫“供应商/模型”；内部 Artist `vendor` 可以保留为实现细节，但 GUI 与 CLI 不应混用。
5. **开发者入口降级。** 维护标注（2026-06-30）：旧 `writer agent/tool/debug/message/step` 顶层入口已删除。
6. **桌面路线需要收敛。** Writer 同时存在 Electron 与 Tauri，Artist 是 pywebview；作为长期产品应明确每个 member 的主桌面路线，其他路线标为实验或删除候选。

## 第三步：文档产物

- CLI 文档：`docs/cli-guide.md`
- GUI 文档：`docs/gui-guide.md`

这两份文档按当前源码改写，避免继续传播旧文档里的过期命令。
