<!-- codex-workflow-id: viettran-edgeAI/codex_workflow -->
<!-- codex-workflow-managed-start -->
# AGENTS.md

## Design Principles

- Keep modules cohesive, interfaces explicit, coupling minimal, and behavior
  testable, replaceable, and reusable.
- Define proportionate acceptance and verification before implementation. Never
  weaken coverage, assertions, or failure visibility to save time or tokens.
- Avoid unnecessary process or safeguards; preserve unrelated user work and use
  verified facts in durable documentation.

## Working State

-`deployment state` : planning or executing a broad, possibly multi-session deployment plan.
- `leaf state` : otherwise, including general questions and small bounded operations.

## Project Documentation

Use the durable project documents under `agent_docs/`:

- `project_overview.md`: goals, architecture, workflow, and major decisions.
- `project_core_tech.md`: concise special technology or architecture notes.
- `project_structure.md`: layout, modules, components, and ownership.
- `project_progress.md`: goal, overall progress, current position, next milestone.
- `project_diary.md`: distilled decisions, discarded approaches, mistakes, and
  reusable lessons.
- `latest_session_work.md`: detailed handoff evidence and continuation point.
- Module-specific documents, when present.

In deployment state, you own `project_diary.md` and record only lasting
decisions, discarded approaches, mistakes, and reusable lessons. Archivist owns
assigned project and public documentation from verified facts, including
overview, structure, core technologies, and closing updates to progress and
latest-session documents. Assign module documents explicitly. Perform a direct
user-requested document edit yourself outside deployment.

Keep raw logs, temporary reasoning, and short-lived checkpoints out of durable
documents; give each fact one canonical home. Never delete a main project
document without warning and a second explicit confirmation.

## Route Selection

Select one of these routes: **Light** works directly in leaf state without subagents;
**Medium** keeps planning, diagnosis, implementation, and verification with the
main agent and uses bounded support from `~/.codex/codex_workflow/medium_route.md`;
**Heavy** delegates bounded production, verification, documentation,
project-context, and Internet research under `~/.codex/codex_workflow/heavy_route.md`.

Follow the user's route selection. Use Light when none is selected; do not infer
Medium or Heavy. Keep the route until the user changes it or the session ends.
Enter deployment state for Medium or Heavy only when the work is substantive.

## Rollout Efficiency

Batch independent reads, searches, metadata checks, and other known-input
operations. Keep dependencies and overlapping mutations sequential. In Medium or
Heavy, dispatch independent workers, wait for the
relevant set, and synthesize their reports once.

Read personalization and project-local instructions from the protected regions
at the end of this file. Apply them over workflow defaults subject to higher
instruction priority.

## Required Documentation Read

On the first `deployment state` entry under either route, before planning,
modifying files, or dispatching a worker, directly read the complete current
`agent_docs/` framework exactly once: overview, core technology, structure,
progress, diary, latest session work.

This is one shared session-level read across both routes; reuse it for later
deployments and route changes. Assign Companion a bounded delta or conflict
check when documentation changes or freshness matters. Missing or unreadable
required documents leave deployment entry incomplete; report the intake blocker.

## Platform Paths

Interpret `/` as a platform-neutral separator and translate paths for the
current operating system and shell.
<!-- codex-workflow-managed-end -->

<!-- codex-workflow-project-personalization-start -->
<!-- codex-workflow-project-personalization-end -->

<!-- codex-workflow-project-local-instructions-start -->
# LamTools

## 沟通方式（强制）

- 面向用户的回复只讲业务：发生了什么（用户能观察到的现象）、现象之间的差别、以及需要用户拍板的业务决策及其影响。
- 不出现代码路径、函数名、变量名、日志片段、协议或接口名等实现层词汇；实现方案与取舍由 agent 自行决定，不向用户汇报。
- 仅当用户明确要求技术细节（看代码、代码审查、排查细节）时，才按要求的粒度展开。

## Setup 后置验收

- 每次完成 Core Windows Inno Setup 构建（`core/desktop/installer/Sunday.iss`）或 setup 版本更新后，使用项目技能
  `.agents/skills/lamtools-setup-install`，将对应版本安装到
  `E:\setuptest\<版本号>`，启动并校验主程序与后端进程；不要改用开发模式启动代替。

## 项目结构

- **Core** (`core/`)：Agent 基座，一个基础独立可用的 Agent。当前唯一活跃产品。
- **Website** (`website/`)：官网（Vue 3 + Vite + anime.js）。独立构建，但展示区通过 alias 复用 `core/ui/src` 与 `core/ui/node_modules`，构建前需先 `cd core/ui && npm ci`。
- **Archive** (`archive/members/`)：已归档的 member 产品（Writer / Sage / Imager），保留历史可追溯，不再维护。

## 核心规则

- **产品定位：LamTools 的目标是通用的一站式 AI 应用；工作流是支撑多种 AI 场景的基础能力，AI 漫剧只是其中一个应用场景，不是产品定位。**
- **任何计划都必须先与用户全方面达成共识之后才能实现；如有任何不确定之处，请先询问用户。**
- 当前聚焦 Core 建设，所有改动在 `core/` 内进行。
- 任何 GUI 能力必须有对应的 CLI。
- PowerShell 涉及中文必须使用 UTF-8。
- **观测环境只有 Tauri**（`core/desktop`），一切 UI 验证以 Tauri 窗口为准，不折腾浏览器/dev.ps1 体系。
- **默认只做代码级检查**：开发与修复过程中不主动用浏览器或任何 GUI 工具查看界面；要看渲染效果必须先得到用户明确许可。UI 的实际观感由用户在 Tauri 窗口里确认。

## 移动端发布节奏

- **0.1.x 就是移动端测试通道**：每完成一次修复，补丁号直接 +1（0.1.9 → 0.1.10 → 0.1.11 …），出包并上传，供真机验证；不需要每次再问是否发版。
- 版本号 8 处同步：`core/mobile/package.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`、`src-tauri/Cargo.lock`（`sunday-mobile`）、`gen/android/app/build.gradle.kts`（versionCode/versionName 默认值）、`gen/android/app/tauri.properties`、`update-manifest.json`，以及官网 `website/src/components/Download.vue` 的 `VITE_SUNDAY_MOBILE_VERSION` 默认值。
- Android versionCode = major*1000000 + minor*1000 + patch（0.1.9 → 1009）；`scripts/package-mobile.ps1` 会校验它。
- 发布流程与审计沿用 `core/mobile/artifacts/release-0NN/`：出包 → 独立校验 APK → 上传 APK 与官网 → 公开校验。注意 `package-mobile.ps1` 的 stdout 会被 Gradle daemon 持有，管道读取会等不到 EOF（表现为"卡住"），应改为重定向到文件并轮询产物。

## 官网（website/）

- 技术栈：Vue 3.5 + Vite 8 + TS 6 + anime.js v4（动效）+ lucide-vue-next（图标）。
- **产品展示区 = 真实 UI（iframe 预览）**：`preview.html` + `src/preview-main.ts` 在同一站点内挂载真实的 `core/ui` `LamToolsApp`（含内置 Workflow UI），`Showcase.vue` 用一个常驻 iframe 承载它并用 postMessage 同步主题（换 URL 会让宿主页面滚动）；真实组件与 CSS 仍来自 `core/ui/src`，模拟数据按真实 `CoreMessage/MessagePart` 形状驱动。改 UI 前先看这里，勿手写仿造。
- 关键坑：① vue 必须 alias 到 website 自己的单例（否则 core/ui 组件加载第二份 vue 白屏）；② ChatThread 消息列表 `v-memo` 依赖消息对象引用——原地改 parts 不重渲染，每次变更要提交**新消息对象**（`commitMsg`）；③ 答案 part 用 `model_text`，`msg.content` 存最终全文（真实数据模型）；④ 覆盖真实组件 DOM 的样式要放全局（如 `preview.html` 里的 `.core-preview-document .thread` 贴底呈现——scoped 属性选择器匹配不到 WorkspaceShell 渲染的节点）；⑤ `@vue-flow/*` 等依赖由 vite alias 指向 `core/ui/node_modules`，构建前必须先装 core/ui。
- 开发：`cd website && npm run dev`（5199，不碰 5172/5173）；构建 `npm run build`（纯 vite build，因 core/ui 跨项目类型检查噪音大未挂 vue-tsc）；产物 `website/dist/`。
- 版本引用：`Download.vue` 的 `VITE_SUNDAY_VERSION`（桌面）与 `VITE_SUNDAY_MOBILE_VERSION`（移动端）默认值随发布更新，`.env.example` 与 `src/mock/runtime.ts` 里的预览版本同步跟着走。
- 文案不再使用 `TODO(文案)` 占位标记；下载区安装包路径指向站点 `downloads/`（`Sunday-latest-x64-setup.exe` 与版本化文件都在站点上）。
- **公网 `ainarit.com` 用的是另外两份副本，发布必须同步**：站点发布只重指 `/var/www/lamtools/site`（`47.114.43.99.nip.io`），而注册域名另有 `/var/www/ainarit/sunday.html`（下载区版本标签与 Linux 链接写死在页面里）与 `/var/www/ainarit-preview`（`/preview/` 内嵌的产品界面）。发布后执行 `scripts/sync-public-site.sh`（服务器上已装到 `/usr/local/bin/`）：它按刚发布的两个 manifest 打版本标签、用已发布的站点包重建 `/preview/`、并回访公网确认；`--check` 只读，脱节时退出码 1，可作验收关卡。历史上漏掉这一步导致页面停在 0.3.10 且两条 Linux 链接 404，详见 `core/desktop/artifacts/release-0.3.15/public-site-sync.md`。

## 开发启动

```powershell
.\scripts\dev.ps1 core              # Core 前后端 (5172 / 5173)
.\scripts\dev.ps1 all               # 同上（Core-only）
.\scripts\restart.ps1               # 重启 Core 前后端（仅 dev.ps1 体系）
```

## 本地开发工具

- Android SDK / ADB：`E:\Environment\AndroidSDK`；`adb.exe` 位于其 `platform-tools`，系统已配置 `ANDROID_HOME`。
- Android Gradle 使用 JDK 21：`C:\Users\Administrator\AppData\Roaming\.minecraft\runtime\java-runtime-delta`；构建 `core/mobile/android` 前将本次 PowerShell 进程的 `JAVA_HOME` 指向该目录，不要使用现有 Java 8 或 JDK 17。

## Tauri（唯一观测环境）

- **不要用 `restart.ps1` / dev.ps1 管 Tauri**：`restart.ps1` 杀 5173 会误杀 Tauri dev 的 vite，破坏其加载链（Tauri 窗口 devUrl 写死 `127.0.0.1:5173`，前端由 `core/desktop` 的 vite 服务）。
- Tauri dev 是独立体系：Rust 自己选随机空闲端口拉起后端（`py -3.14 -m lamtools_core.cli serve --port 随机 --reload`，cwd=`core/`，同一份 `data/core.db`），前端 `__LAMTOOLS_API_BASE__` 由 Rust `get_api_base` 下发，不走 5172/代理。
- **Tauri 前后端重启 = 完全退出后在 `core/desktop` 下重新 `npm run tauri dev`**。重启前先确认 5173 没有别的 vite 占着（否则 desktop vite 抢不到端口挪到 5174，窗口仍加载 5173 会拿到错误页面）。
- UI 改动经 HMR 即时生效（desktop 入口 `src/main.ts` 直接 import `../../ui/src/app/LamToolsApp.vue`，`core/ui/src` 全部在依赖链上）；打包产物（`tauri build`）无热更新。

## 数据库与配置

| 组件 | 路径 |
|------|------|
| Core 会话/运行时 | `data/core.db` |

- **模型 / 供应商 / 设置只有 jsonc，无 config DB**：模型 `models/<model_id>.jsonc`、供应商 `providers/<id>.jsonc`、设置 `settings.jsonc`、模型重试 `model_retry.jsonc`，统一在 `.lam/core/config/`（`LAMTOOLS_CORE_CONFIG_ROOT` 可覆盖）。禁止再引入 `llm_providers` / `llm_models` / `app_settings` 表或 `LAMTOOLS_LLM_CONFIG_DB` 环境变量。
- 模型重试参数（次数/单次超时/流式空闲超时/空响应重试/每次重试间隔 `retry_delays_seconds`/抖动）读 `model_retry.jsonc`，缺省即代码内默认值；装配点 `default_agent.create_kernel`、`cli.py`、`tool/sub_agent_runner.py` 读取，显式传参优先于配置文件。
- 供应商 api_key 明文存于 `providers/*.jsonc`；RPC 列表接口返回打码 `********`，写回时打码/空值不覆盖原 key。
- **默认配置播种**（`config/defaults.py` 的 `ensure_default_config_files`，幂等不覆盖）：loadtools/access_tools/hooks/mcp/README 从 `core/config/resources/` 复制，AGENTS.md/load_context/model_retry/subagent 由代码内默认写入，并创建全局记忆库目录 `memory/`。安装器**不打包 `.lam`**（曾打包过，NSIS 覆盖语义会抹掉用户配置——已移除），新增默认文件一律放 `core/config/resources/` 并注册到播种清单。
- **记忆 = 两档目录 + 工具驱动**（`mem/library.py`）：项目档 `<work_root>/.lam/memory/`、全局档 `.lam/core/config/memory/`；目录结构即索引，每档的 `INDEX.md` 由目录结构全自动生成、注入每个会话（优先级 15 / 20），模型通过内置 `memory` 工具（`tool/memory_tools.py`，auto_allow）读写。人工入口：资料库 → 记忆（浏览/编辑，项目档先列项目这一层）；设置与项目设置不再有记忆分区。`memory.reveal` RPC / `core memory reveal`（`--global` 切全局）仍可调起系统文件资源管理器打开对应文件夹；`memory.*` RPC 与 `core memory tree/read/write/append/edit/delete/rename/mkdir` 供模型与脚本读写。`INDEX.md` 是保留名，任何入口都不可写/改名/删除。旧的做梦（dreaming）、结构化记忆库（`core_memories` 表）与 `memory.md` / `MEMORY.md` 注入已整体移除，不再兼容。
- **软件更新 = 检测 + 应用内下载校验 + 交给系统安装程序**：`update.check` RPC / CLI `lamtools_core.cli update check` → 后端 `update/checker.py` 先读官网清单（`downloads/desktop-update.json`）、再回退 GitHub `releases/latest`，与 `lamtools_core.__version__` 比较。有新版本时，左侧竖栏（账号上方）出现一枚柔和圆角的更新图标；点它，图标平移放大成屏幕中央的更新卡片：卡片写明当前版本 → 最新版本、更新摘要（有则显示）、下载百分比，并提供「取消」与「更新」。点「更新」后下载（`update.download`，逐块校验摘要；`update.cancel` 可中途取消）→ 校验通过即自动安装（`update.install`，`/SILENT` + `/AUTORESTART=1`）→ **Windows 上应用先自行退出再运行安装包**（安装程序以脱离后端作业对象 `JOB_OBJECT_LIMIT_BREAKAWAY_OK` 的方式启动）→ **装完由安装程序自动把应用重新打开**；Linux/macOS 只打开安装包所在文件夹且不退出（`quit: false`）。发布流程必须跑 `scripts/verify-update-install.ps1`（公网下载 + 摘要一致 + 静默安装 + 应用自动回来），CI 侧由 `verify-desktop-lifecycle.ps1` 覆盖同一契约。**版本号 5 处必须同步**（tauri.conf.json / Cargo.toml / desktop package.json / pyproject.toml / `__init__.py`），统一用 `scripts/bump-version.ps1`，打 tag `vX.Y.Z` 后 `release.yml` 自动出包。不做 updater 插件/签名（详见 `core/desktop/PACKAGING.md`）。

## 持续事项

- Core UI 流式性能优化（卡顿调查、各包实施记录）的唯一权威文档：`docs/core-ui-streaming-perf.md`。每次相关改动或新会话必须先读它。
  - 快速见效包（delta 合并 / 滚动合并 / goal 节流 / watcher 裁剪）已完成。
  - 结构包（MessageView 组件化 + 投影增量更新 + Markdown 增量分段渲染）已完成（2026-08-07）。
  - part 级 v-memo 隔离（5 处 part 循环元素级 v-for + v-memo）已完成（2026-08-07）。
<!-- codex-workflow-project-local-instructions-end -->
