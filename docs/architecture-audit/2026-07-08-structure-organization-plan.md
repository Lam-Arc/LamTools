# LamTools 项目结构整理方案

日期：2026-07-08

维护标注（2026-07-08）：本报告写于非 Writer 成员下线之前。后续已将未验证成员从当前产品面移除，Artist 相关模块分析仅作为历史证据和未来从 0 重做的反面依据，不再代表当前活跃项目结构。

## 真实目标

这次梳理不是新增功能，而是为后续减法重构建立可复核底图：先把 LamTools 的活跃模块、历史资产、入口和边界分清，再逐模块判断哪些属于可靠主线、哪些属于自研但仍可保留、哪些属于收益为负的债务。

## 验收标准

- 每个主要模块都有独立报告文档。
- 每份模块报告都包含：职责、主要入口、路径覆盖、关键依赖、可靠/存疑/债务判断、可删除或可合并点、重构优先级。
- 总报告给出项目级结构整理方案、跨模块问题、优先级路线和不建议现在做的事。
- 统计口径使用当前工作树，但只统计 Git 已跟踪的活跃源码和测试；不把打包产物、运行数据、截图、历史 E2E 输出当作产品模块。
- 不修改业务代码，不处理当前未提交的用户改动。

## 当前工作树状态

当前工作树不是干净状态：

- 已修改：`members/writer/frontend/src/views/CoreWorkbenchView.vue`
- 未跟踪：`docs/prototypes/`
- 未跟踪：`members/writer/frontend/tests/runtime/runtimeResourceWidget.test.ts`

本轮只新增架构梳理报告，避免覆盖或解释这些既有改动。

## 统计底表

活跃生产源码范围：

- `core/src`
- `core/ui/src`
- `members/writer/backend/app`
- `members/writer/backend/writer_cli`
- `members/writer/backend/writer_tui`
- `members/writer/frontend/src`
- `members/writer/frontend/electron`
- `members/writer/frontend/scripts`
- `members/writer/frontend/src-tauri/src`
- `members/artist/backend/app`
- `members/artist/frontend/src`
- `members/artist/desktop`
- `scripts`
- 根入口文件：`writer.cmd`、`artist.cmd`、`lamtools.cmd`、`start.bat`、`README.md`、`PRODUCT.md`、`AGENTS.md`

测试范围：

- `core/tests`
- `core/ui/tests`
- `members/writer/backend/tests`
- `members/writer/frontend/tests`
- `members/artist/backend/tests`
- `tests`
- `e2e/tests`

当前统计：

| 范围 | 文件数 | 总行数 | 非空行 |
| --- | ---: | ---: | ---: |
| 生产源码 | 398 | 80,438 | 71,089 |
| 测试 | 131 | 40,484 | 34,100 |
| 合计 | 529 | 120,922 | 105,189 |

主要区域非空行：

| 区域 | 文件数 | 非空行 |
| --- | ---: | ---: |
| Core 后端协议/运行骨架 | 60 | 11,393 |
| Core UI | 33 | 10,167 |
| Writer 后端 | 123 | 20,037 |
| Writer CLI/TUI | 3 | 1,098 |
| Writer 前端 | 27 | 8,942 |
| Writer 桌面/脚本 | 13 | 1,783 |
| Artist 后端 | 88 | 12,090 |
| Artist 前端 | 29 | 4,324 |
| Artist 桌面 | 5 | 442 |
| 脚本和根入口 | 17 | 813 |

当前最大热点：

| 文件 | 非空行 | 判断 |
| --- | ---: | --- |
| `core/ui/src/components/ChatThread.vue` | 3,896 | 共享展示层过深，需拆投影/渲染职责 |
| `members/writer/frontend/src/views/CoreWorkbenchView.vue` | 3,365 | Writer 工作台承载过多页面协调职责 |
| `core/ui/src/styles/layout.css` | 2,609 | 共享样式集中度过高 |
| `members/writer/frontend/src/views/SettingsView.vue` | 2,066 | 设置页仍有临时隐藏区和旧配置压力 |
| `members/writer/backend/app/app_server/operations.py` | 2,041 | Writer app-server 操作目录过宽 |
| `core/src/lamtools_core/kernel/loop.py` | 1,506 | 主循环大但仍是核心主线，先谨慎拆内部私有块 |

## 模块拆分

本次拆 8 个模块，按维护边界而不是按目录机械切分：

1. Core 后端协议与运行骨架：`core/src`、`core/templates`、`core/docs`
2. Core UI 共享工作台：`core/ui/src`、`core/ui/tests`
3. Writer 后端、运行时与 CLI：`members/writer/backend/app`、`writer_cli`、`writer_tui`
4. Writer 前端、桌面与 app-server 客户端：`members/writer/frontend/src`、`electron`、`src-tauri/src`、前端脚本
5. Artist 后端、运行时与桌面：`members/artist/backend/app`、`members/artist/desktop`、`build.py`
6. Artist 前端：`members/artist/frontend/src`
7. 脚本、根入口与成员脚手架：`scripts`、根 `*.cmd`、`start.bat`
8. 文档、测试、样例与历史资产：`docs`、`tests`、`e2e/tests`、`e2e/test-apps`、`test-*`

## 判断标准

### 可靠

符合当前主线架构，职责明确，接口小，能被多个产品复用，或和成熟 Agent/LLM 工程实践一致。

### 存疑

功能闭环存在，但接口偏宽、历史状态未收敛、职责混合、缺少足够验证，或需要先对照成熟方案再决定保留方式。

### 债务

并行旧入口、重复投影、运行产物混入源码视野、只靠补丁维持行为、Core 泄露产品语义、文件巨大且修改风险高，或可以通过已有功能直接替代。

## 结构整理原则

- Kernel 管流程，Kit 管业务；不要恢复 Hook 式平行层。
- Core 只放通用协议、运行骨架、共享 UI 和基础能力；产品 persona、业务路由、专用展示留在 member。
- 优先合并重复入口和删除旧兼容层，再谈新增抽象。
- 共享模块要深：对外接口更小，内部实现可以分块；不要把浅 wrapper 当成架构层。
- 历史文档不静默改写，新增维护标注说明当前状态。
- GUI 能力必须有同接口 CLI。
- 进入任何实际改造前，再按具体模块对照 OpenAI/Claude 成熟方案，避免自研补丁替代已有协议。

## 子 agent 分工

每个子 agent 只读自己的模块和必要调用方，输出 Markdown 报告内容；主线程统一写入文档并做冲突校准。

交付路径计划：

- `docs/architecture-audit/modules/2026-07-08-core-backend.md`
- `docs/architecture-audit/modules/2026-07-08-core-ui.md`
- `docs/architecture-audit/modules/2026-07-08-writer-backend.md`
- `docs/architecture-audit/modules/2026-07-08-writer-frontend.md`
- `docs/architecture-audit/modules/2026-07-08-artist-backend.md`
- `docs/architecture-audit/modules/2026-07-08-artist-frontend.md`
- `docs/architecture-audit/modules/2026-07-08-scripts-entrypoints.md`
- `docs/architecture-audit/modules/2026-07-08-docs-tests-assets.md`
- `docs/architecture-audit/2026-07-08-lamtools-architecture-summary.md`
