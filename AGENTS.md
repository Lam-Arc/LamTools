# LamTools

## 项目结构

- **Core** (`core/`)：Agent 基座，一个基础独立可用的 Agent。当前唯一活跃产品。
- **Website** (`website/`)：官网（Vue 3 + Vite + anime.js），独立构建，不参与 core 开发链路。
- **Archive** (`archive/members/`)：已归档的 member 产品（Writer / Sage / Imager），保留历史可追溯，不再维护。

## 核心规则

- **任何计划都必须先与用户全方面达成共识之后才能实现；如有任何不确定之处，请先询问用户。**
- 当前聚焦 Core 建设，所有改动在 `core/` 内进行。
- 任何 GUI 能力必须有对应的 CLI。
- PowerShell 涉及中文必须使用 UTF-8。
- **观测环境只有 Tauri**（`core/desktop`），一切 UI 验证以 Tauri 窗口为准，不折腾浏览器/dev.ps1 体系。

## 官网（website/）

- 技术栈：Vue 3.5 + Vite 8 + TS 6 + anime.js v4（动效）+ lucide-vue-next（图标）。
- **产品展示区 = 真实 UI 直挂**：`Showcase.vue` 直接 import `core/ui/src` 的真实组件（WorkspaceShell/SessionSidebar/ChatThread/CoreExecutionControls/CoreResourceStats/CoreSessionTitleEditor/TitleBar）与真实 CSS（variables/base/layout），用 `transform: translateZ(0)` 把 position:fixed 的 shell 装进窗口卡片，模拟数据按真实 `CoreMessage/MessagePart` 形状驱动。改 UI 前先看这里，勿手写仿造。
- 关键坑：① vue 必须 alias 到 website 自己的单例（否则 core/ui 组件加载第二份 vue 白屏）；② ChatThread 消息列表 `v-memo` 依赖消息对象引用——原地改 parts 不重渲染，每次变更要提交**新消息对象**（`commitMsg`）；③ 答案 part 用 `model_text`，`msg.content` 存最终全文（真实数据模型）；④ 覆盖真实组件 DOM 的样式要放全局（如 `.mock-window .thread { align-content: end }` 贴底呈现——scoped 属性选择器匹配不到 WorkspaceShell 渲染的节点）。
- 开发：`cd website && npm run dev`（5199，不碰 5172/5173）；构建 `npm run build`（纯 vite build，因 core/ui 跨项目类型检查噪音大未挂 vue-tsc）；产物 `website/dist/`。
- 注意：本仓库 headless 验证环境里 IntersectionObserver 只在 observe 时回调一次——入场动效统一走 `utils/inView.ts` 的 scroll+rAF 检测（`useScrollReveal` / Architecture 均用它），新增动效不要依赖 IO。
- 全部文案是占位，标 `TODO(文案)`；下载区安装包路径待发布后替换。

## 开发启动

```powershell
.\scripts\dev.ps1 core              # Core 前后端 (5172 / 5173)
.\scripts\dev.ps1 all               # 同上（Core-only）
.\scripts\restart.ps1               # 重启 Core 前后端（仅 dev.ps1 体系）
```

## Tauri（唯一观测环境）

- **不要用 `restart.ps1` / dev.ps1 管 Tauri**：`restart.ps1` 杀 5173 会误杀 Tauri dev 的 vite，破坏其加载链（Tauri 窗口 devUrl 写死 `127.0.0.1:5173`，前端由 `core/desktop` 的 vite 服务）。
- Tauri dev 是独立体系：Rust 自己选随机空闲端口拉起后端（`py -3.14 -m lamtools_core.cli serve --port 随机 --reload`，cwd=`core/`，同一份 `data/core.db`），前端 `__LAMTOOLS_API_BASE__` 由 Rust `get_api_base` 下发，不走 5172/代理。
- **Tauri 前后端重启 = 完全退出后在 `core/desktop` 下重新 `npm run tauri dev`**。重启前先确认 5173 没有别的 vite 占着（否则 desktop vite 抢不到端口挪到 5174，窗口仍加载 5173 会拿到错误页面）。
- UI 改动经 HMR 即时生效（desktop 入口 `src/main.ts` 直接 import `../../ui/src/demo/App.vue`，`core/ui/src` 全部在依赖链上）；打包产物（`tauri build`）无热更新。

## 数据库与配置

| 组件 | 路径 |
|------|------|
| Core 会话/运行时 | `data/core.db` |

- **模型 / 供应商 / 设置只有 jsonc，无 config DB**：模型 `models/<model_id>.jsonc`、供应商 `providers/<id>.jsonc`、设置 `settings.jsonc`、模型重试 `model_retry.jsonc`，统一在 `.lam/core/config/`（`LAMTOOLS_CORE_CONFIG_ROOT` 可覆盖）。禁止再引入 `llm_providers` / `llm_models` / `app_settings` 表或 `LAMTOOLS_LLM_CONFIG_DB` 环境变量。
- 模型重试参数（次数/单次超时/流式空闲超时/空响应重试/每次重试间隔 `retry_delays_seconds`/抖动）读 `model_retry.jsonc`，缺省即代码内默认值；装配点 `default_agent.create_kernel`、`cli.py`、`tool/sub_agent_runner.py` 读取，显式传参优先于配置文件。
- 供应商 api_key 明文存于 `providers/*.jsonc`；RPC 列表接口返回打码 `********`，写回时打码/空值不覆盖原 key。
- **默认配置播种**（`config/defaults.py` 的 `ensure_default_config_files`，幂等不覆盖）：loadtools/access_tools/hooks/mcp/README 从 `core/config/resources/` 复制，AGENTS.md/load_context/memory/model_retry/subagent 由代码内默认写入。安装器**不打包 `.lam`**（曾打包过，NSIS 覆盖语义会抹掉用户配置——已移除），新增默认文件一律放 `core/config/resources/` 并注册到播种清单。
- **软件更新 = 检测 + 引导下载**（非静默安装）：`update.check` RPC / CLI `lamtools_core.cli update check` → 后端 `update/checker.py` 调 GitHub API `releases/latest` 与 `lamtools_core.__version__` 比较；前端「设置 → 关于与更新」展示并引导下载（`__LAMTOOLS_OPEN_URL__` 打开浏览器）。**版本号 5 处必须同步**（tauri.conf.json / Cargo.toml / desktop package.json / pyproject.toml / `__init__.py`），统一用 `scripts/bump-version.ps1`，打 tag `vX.Y.Z` 后 `release.yml` 自动出包。不做 updater 插件/签名（详见 `core/desktop/PACKAGING.md`）。

## 持续事项

- Core UI 流式性能优化（卡顿调查、各包实施记录）的唯一权威文档：`docs/core-ui-streaming-perf.md`。每次相关改动或新会话必须先读它。
  - 快速见效包（delta 合并 / 滚动合并 / goal 节流 / watcher 裁剪）已完成。
  - 结构包（MessageView 组件化 + 投影增量更新 + Markdown 增量分段渲染）已完成（2026-08-07）。
  - part 级 v-memo 隔离（5 处 part 循环元素级 v-for + v-memo）已完成（2026-08-07）。
