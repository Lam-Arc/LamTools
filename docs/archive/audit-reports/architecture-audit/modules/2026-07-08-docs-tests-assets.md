# 文档、测试、样例与历史资产

## 一句话结论

这个区域最大问题不是缺文档，而是“入口文档、历史计划、一次性报告、样例工程、测试残留”混在主视野里。测试主线基本存在，但统一入口不完整；样例和历史 E2E 产物应从产品模块视野里排除，优先归档、标注或删除。

本轮只读分析，未改文件，未运行测试。

## 路径覆盖

- `docs`：69 个跟踪文件，约 27,646 非空行。
- `members/writer/docs`：34 个跟踪文件，约 14,137 非空行。
- `members/artist/docs`：24 个跟踪文件，约 8,089 非空行。
- `tests`：5 个跟踪文件，旧 Playwright/截图/streaming 验证。
- `e2e/tests`：2 个 smoke spec，Writer/Artist 各一套。
- `e2e/test-apps`：58 个跟踪文件，约 13,178 非空行，更像历史任务样例库。
- `test-*`：`test-blog-project`、`test-mod-site`、`test-tool-result-demo`、`test-website-demo`、`test-website-demo2` 有跟踪文件；`test-output`、`test-results` 当前无跟踪文件。
- `kbtool-task`：7 个跟踪文件，独立 Markdown KB 小工具，不属于 LamTools 主产品。
- 已看：`.gitignore`、`README.md`、`AGENTS.md`、`docs/architecture-audit/2026-07-08-structure-organization-plan.md`。

## 主要职责和入口

当前维护入口应收敛到：

- 项目入口：`README.md`、`AGENTS.md`。
- 文档索引：`docs/documentation-inventory.md`，但它是 2026-06-29 口径，需要更新到当前结构。
- 测试说明：`docs/test-layering.md`，但它和 `scripts/test.ps1` 现状不完全一致。
- 架构主线：`docs/agent-architecture-north-star-2026-06-30.md`、`docs/core-member-architecture-refactor-design-2026-06-30.md`、`docs/core-member-architecture-refactor-execution-plan-2026-07-01.md`。
- 路径底图：`docs/agent-code-inventory-2026-06-30.md`。
- 使用入口：`docs/cli-guide.md`、`docs/gui-guide.md`、`docs/tech-stack-baseline.md`。

历史/计划/预览/一次性报告：

- `docs/bug-audit-*`、`code-quality-audit-*`、`fix-plan-*`、`codex-handoff-*`、`writer-*-audit/fix-plan/report` 多为一次性审查或修复记录。
- `docs/plans/**`、`docs/stages/**`、`docs/superpowers/plans/**`、`docs/superpowers/specs/**` 是实施记录和方案，不应作为当前事实入口。
- `members/writer/docs/*preview.html`、`writer-card-stack-motion-demo.html`、`quality-wheel-preview.html` 等是 UI 预览资产。
- `members/writer/docs/PLAN.md`、`ROADMAP.md` 出现 Artist/lamartist 历史内容，不能直接当 Writer 当前入口。
- `members/artist/docs/ROADMAP.md`、`progress-log.md`、`learning-report.md` 有历史价值，但要标注当前适用范围。

测试层级现状：

- Core 后端：`core/tests`，覆盖 Kernel、LLM、工具、事件、快照、session、provider、sub-agent 等。
- Core UI：`core/ui/tests`，有 Vitest/contract 入口，但 `scripts/test.ps1` 不跑它。
- Writer 后端：`members/writer/backend/tests`，主测试密集，但仍有 `algo_score.py`、`env_probe.py`、`check_msgs.py` 这类非 `test_*.py` 脚本混在测试目录。
- Writer 前端：`members/writer/frontend/tests`，通过前端 `npm test` 跑 app-server/runtime 测试。
- Artist 后端：`members/artist/backend/tests`，覆盖 unit/e2e 混合；部分名称仍带 Hook/ExecutionEngine 旧语义。
- Artist 前端：当前没有独立前端测试脚本。
- E2E smoke：`e2e/tests`，通过 `e2e/package.json` 的 `npm run test:smoke`，依赖已启动的 6174/5174 前端。
- 根 `tests`：旧 Playwright spec 和 mock html，和 `e2e/tests` 职责重叠。

## 可靠

- `README.md` + `AGENTS.md` 给出了清楚的 monorepo 边界、执行规则和常用入口。
- `docs/agent-code-inventory-2026-06-30.md`、`docs/core-member-architecture-refactor-design-2026-06-30.md` 已经有大量维护标注，是当前减法和路径覆盖的重要底图。
- Core / Writer / Artist 后端测试目录都存在，能支撑按模块回归。
- `e2e/tests` 的 Writer/Artist smoke 分层清楚，不把历史样例项目当运行入口。
- `.gitignore` 已排除 `.archives/`、`.codex-runtime/`、`.writer-artifacts/`、`tmp/`、打包输出等主要运行产物。

## 存疑

- `docs/documentation-inventory.md` 仍有价值，但它早于 7 月结构整理，未覆盖当前 `docs/architecture-audit/` 报告和最新入口状态。
- `docs/test-layering.md` 说 Writer 后端不要全量 pytest，但 `scripts/test.ps1 writer` 实际跑整个 `members/writer/backend`；入口说明和执行脚本冲突。
- `docs/superpowers/**` 是近期实施规格，但目前在主 `docs` 下占据大量视野，应标为“实施记录”，不要变成架构入口。
- `members/artist/docs/api/architecture/runbook` 有产品文档价值，但英文/中文双份容易漂移。
- `kbtool-task` 有 README 和测试，作为独立练习/夹具可保留，但与 LamTools 主产品边界不清。

## 债务

- `e2e/test-apps` 是最大样例债务：58 个跟踪文件、1.3 万非空行，且 smoke spec 不直接引用它们。
- 根 `test-*` 与产品目录同级，且部分目录内还跟踪 `.writer-artifacts/mcp/playwright/*.yml`，运行证据混进源码视野。
- 根 `tests` 与 `e2e/tests` 职责重叠，且没有根 Playwright config；应迁移或删除。
- Writer 文档区历史包袱重：`PLAN.md`、`ROADMAP.md` 带 Artist 内容，多个 preview/demo HTML 不应出现在当前维护入口。
- 大文档 `docs/core-member-architecture-refactor-design-2026-06-30.md` 是必要历史账本，但体量过大，应有摘要入口，否则后续 agent 会被执行流水淹没。
- `.gitignore` 没有排除 `test-*`、`e2e/test-apps`、`test-output`、`test-results`，旧审计也已经建议补充。

## 重构/优化建议

### P0

- 更新 `docs/documentation-inventory.md`：明确“当前入口 / 历史审计 / 实施计划 / 预览资产 / 样例资产”五类。
- 给 `members/writer/docs/PLAN.md`、`ROADMAP.md` 加维护标注或迁出，说明其中 Artist/lamartist 内容不代表 Writer 当前状态。
- 将 `e2e/test-apps`、根 `test-*`、`kbtool-task` 从主产品视野中归为 `fixtures/archive` 或直接删除候选；先列清单，后决定保留样例。
- 修正测试入口口径：`scripts/test.ps1 all` 不应宣称覆盖全部测试，或补上 Core UI / Writer frontend / e2e smoke 入口。

### P1

- 合并根 `tests` 到 `e2e/tests` 或删除旧 mock spec，保留一个 Playwright smoke 入口。
- 将 `docs/superpowers/plans/specs/previews` 改为“实施档案”分区，入口文档只链接最新相关项。
- Artist 文档中英文双份设定一个主维护语言，另一份只作为翻译或删除候选。
- 从大执行文档抽一页当前状态摘要，历史正文保留，不重写历史。

### P2

- 为样例资产建立最小索引：样例名、用途、是否仍被测试引用、删除条件。
- 给文档加轻量 front matter：`status: current|historical|plan|preview|fixture`，先从高风险文档开始。
- 以后新增真实 E2E 产物默认落 `tmp/` 或专门 artifacts 目录，不进入 Git 跟踪。

## 不建议现在做

- 不建议重写全部历史文档；应保留历史，补维护标注。
- 不建议把所有计划文档合成一本巨型总文档；这会让入口更重。
- 不建议为文档系统先做复杂生成器；当前先靠分类、索引和删除即可。
- 不建议把 `e2e/test-apps` 当测试覆盖补充，它们不是当前 smoke 入口。
- 不建议把 `kbtool-task` 下沉进 Core；它更像独立练习/样例，不是 LamTools 基础能力。

## 需要主线程核对的证据

- `docs/architecture-audit/` 当前新增报告是否统一纳入 Git。
- `scripts/test.ps1 writer` 全量跑 backend 与 `docs/test-layering.md` 的“不要全量 pytest”是否仍冲突。
- `e2e/test-apps` 是否有任何隐性人工验收价值；代码引用只看到历史文档和个别硬编码路径。
- 根 `test-*` 目录是否还需要保留为 Writer 真实任务种子；若保留，应移到样例/fixtures 区。
- `members/writer/docs/PLAN.md`、`ROADMAP.md` 的 Artist 内容是否应归档到 Artist 历史，还是直接标为旧迁移残留。
