---
类型: REPORT
状态: 生效
实施: 待验收
专题: 方案体系
摘要: 方案分类、统一 Skill、资源库方案模块与 Agent 联动的实施记录与证据；含未完成项与既有失败
关联: 方案/Sunday-方案体系与改造-PRD-V1.0.md, 方案/历史方案整理报告.md
---

# Sunday 方案体系与改造 · 实施与验收报告

> 对应 PRD：`方案/Sunday-方案体系与改造-PRD-V1.0.md`（V1.0）。
> 实施时间：2026-11-27。范围：分类与规范、统一 Skill、Library－方案模块、UI 与 Agent 联动、历史方案整理。
> 结论：P0 的三个方面已落地并通过自动化验证；P1 的状态与关联已交付，历史追踪复用文件 / Git，不建独立版本引擎。真实模型行为评测仍为 NOT_RUN（见「已知问题」）。

## 1. 结论摘要

| 方面 | 结果 | 依据 |
| --- | --- | --- |
| 方案分类与编写规范 | PASS | 类型词表、别名、按类型骨架与双状态读写都有后端用例 |
| 统一方案 Skill | PASS（接线） | `plan-docs` 被宿主注册，4 个技能共 32 条评测用例通过静态自检 |
| Library－方案改造 | PASS | 类型/专题/实施筛选、排序、徽章、元数据、导入、导出都有界面用例 |
| UI 与 Agent 联动 | PASS（接线） | 5 个动作产出 `plan-action`，宿主预制上下文提示词并关联会话 |
| 历史方案整理 | PASS | 56 份逐份盘点，未改写任何文件，报告可追溯 |
| 真实模型行为 | UNVERIFIED | 评测只验接线，未用生产模型逐条跑 |

## 2. 交付物

| 交付 | 位置 |
| --- | --- |
| PRD 原文存档 | `方案/Sunday-方案体系与改造-PRD-V1.0.md` |
| 类型体系、双状态、元数据写回、导入 | `core/src/lamtools_core/app/plan_library.py` |
| 方案路由（meta / import） | `core/src/lamtools_core/http/routes.py` |
| 统一方案 Skill | `core/src/lamtools_core/plugins/bundled/plan/skills/plan-docs/SKILL.md` |
| 各类型骨架与写法 | `core/src/lamtools_core/plugins/bundled/plan/skills/references/plan-types.md` |
| 方案库界面 | `core/ui/src/components/PlanLibraryView.vue` |
| 动作提示词 | `core/ui/src/app/planLaunch.ts` |
| 宿主联动（选项目、建会话、关联） | `core/ui/src/app/LamToolsApp.vue`、`core/ui/src/app/useCorePageBindings.ts` |
| 历史方案盘点 | `方案/历史方案整理报告.md` |
| 后端验收用例 | `core/tests/test_plan_docs_system.py` |
| 前端验收用例 | `core/ui/tests/plan-library-types.test.ts`、`core/ui/tests/plan-launch-prompt.test.ts` |

## 3. 按 PRD 条目落地情况

### 3.1 分类与编写规范（PRD §3、§4）

- 一级分类 PRD / SPEC / DESIGN / RESEARCH / EXP / PLAN / AUDIT / REPORT 与扩展分类 ARCH / ADR / RFC / POC / TEST / MIG / SOP / RCA 共用一份词表；扩展分类不出现在一级入口，类型选项里排在后面。
- 类型读取顺序：frontmatter `类型` 优先；没有时按文件名与标题推断（英文代码优先，中文角色词其次）；推断不出就是「未分类」，不猜。
- 新建时按类型给骨架（每类 4–5 个核心小节），类型可留空，空类型保持旧的最小骨架。
- 编写规范的指导性写在 `plan-docs` 与 `plan-types.md`：每类的核心内容、常见错误、篇幅按复杂度决定，不强制章节。

### 3.2 统一 Skill（PRD §5）

- 新增 `plan-docs`：分类词表、编写规范、八项能力（Create / Discuss / Review / Revise / Execute / Verify / Report / Organize）分别落在哪、验收五词表、文件位置。
- 既有 `draft-plan` / `refine-plan` / `execute-plan` 增加类型入口：起草先定类型，修订不换类型，执行仍走读回—核对—装清单。
- 三个旧技能的六节形状保留为 PLAN 类型的完整实例；旧状态词（草稿 / 就绪 / 执行中 / 完成）继续可读，资料库显示为新词（草案 / 生效 / 已归档 / 已废弃）。
- 每个技能 8 条评测用例，共 32 条；`test_plan_plugin.py` 校验技能清单、平台、引用与用例完整性。

### 3.3 Library－方案（PRD §6）

- 保留原「方案」入口，不新建产品模块；文件仍在项目的 `方案/` 目录，读写走普通文件接口。
- 最小元数据落在 frontmatter：`类型`、`状态`、`实施`、`专题`、`摘要`、`收藏`、`关联`。写回只动 frontmatter，正文与其它未知字段原样保留。
- 新增能力：
  - 类型 / 专题 / 实施状态筛选与「最近修改 / 名称 / 类型」排序；
  - 卡片与列表显示类型徽章、专题标签、设计状态与实施状态；
  - 阅读页：目录、同专题与 `关联` 里点名的文档、关联会话、元数据面板、导出与复制全文；
  - 导入：桌面用文件路径走 `POST /plan-library/import`（复制，源文件不动，重名自动加序号）；其它环境用文件内容创建新方案；
  - 状态即归档/废弃，重命名、移动、删除沿用原有能力。
- 没有新增方案对象模型、专用数据库或关系表。

### 3.4 UI 与 Agent 联动（PRD §7、§9）

- 阅读页动作条：讨论、审查、修订、实施、检查落实情况；右键菜单同样提供讨论 / 审查 / 检查 / 复制路径。
- 动作统一由宿主处理：先选项目（复用 `CoreProjectPicker`），切到该项目并新建会话，把带方案路径与动作要求的提示词预制进输入框；发不发由用户按。
- 发起后把会话 id 写回方案的 `关联: 会话:<id>`，不阻塞主流程（失败静默）。
- 提示词抽在 `planLaunch.ts`，五类动作各有一句明确要求；跨项目时给出绝对位置并说明需要访问批准。

### 3.5 生命周期与历史（PRD §8、§10）

- 设计状态与实施状态是两条独立的轴；读取旧文档时按旧状态词推断实施轴，不改文件。
- 状态不是门禁：没有强制流转，也没有审批。
- 版本与历史复用 Git / 文件历史，不建独立版本引擎；重要变更的修改理由写在方案正文或提交信息里。
- 历史方案：生成 `方案/历史方案整理报告.md`，逐份给出类型（标注「推断」）、状态、专题建议与重复候选；未改写、未移动、未删除任何历史文件。

## 4. 验收场景（PRD §14）

| ID | 场景 | 结果 | 证据 |
| --- | --- | --- | --- |
| A01 | 要求 Agent 编写 PRD | PARTIAL | 类型骨架与 Skill 已就绪；真实模型逐条产出为 NOT_RUN |
| A02 | 编写 SPEC / EXP 采用适当结构 | PARTIAL | 同上；骨架与写法见 `plan-types.md`，新建用例覆盖 PRD / SPEC 两种骨架 |
| A03 | 打开 Library－方案并浏览、搜索、筛选 | PASS | `plan-library-types.test.ts` 覆盖类型 / 专题 / 实施筛选与排序；原有 16 条界面用例通过 |
| A04 | 打开历史方案，内容与引用保持有效 | PASS | 扫描 56 份，未改写；读失败的文件降级为标题条目仍可见（`test_plan_library.py`） |
| A05 | 选择方案发起讨论，Agent 获得上下文 | PARTIAL | `plan-action` 事件与提示词用例通过；真实会话投递未自动验收 |
| A06 | 要求修订时修改原文件 | PARTIAL | 修订提示词要求「只改要求的部分、不要另建一份」；`refine-plan` 技能已更新 |
| A07 | 根据 PRD 发起实施 | PARTIAL | 开工 / 实施提示词与执行技能就绪；端到端用例的 goal 安装一步在基线就失败（见 §6） |
| A08 | 检查方案落实情况 | PARTIAL | 提示词要求逐条给 PASS / PARTIAL / FAIL / UNVERIFIED / BLOCKED 与证据 |
| A09 | 新会话继续工作 | PASS | 方案是项目内普通文件，任意会话可读；`关联: 会话:<id>` 写回测试通过 |
| A10 | 导出方案 | PARTIAL | 阅读页有导出（Blob 下载）与复制全文；真实桌面保存路径未点击验证 |
| A11 | 创建一个简单方案 | PASS | 新建可只填名称；类型可留空（界面用例） |
| A12 | 重启后内容与分类保持 | PASS | 元数据在 frontmatter；写回后扫描回读用例通过（未真实重启应用） |

## 5. 自动化验证

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 后端方案体系 | `python -m pytest core/tests/test_plan_docs_system.py -q --allow-dirty` | 15 passed |
| 后端方案库 + 插件 | `python -m pytest core/tests/test_plan_library.py core/tests/test_plan_plugin.py -q --allow-dirty` | 17 passed |
| 开工端到端（守卫） | `python -m pytest core/tests/test_plan_execution_e2e.py::test_the_ui_start_prompt_still_says_what_the_test_drives -q --allow-dirty` | 1 passed |
| 前端方案库 | `cd core/ui && npx vitest run tests/plan-library-view.test.ts tests/plan-library-types.test.ts tests/plan-library-global.test.ts tests/plan-launch-prompt.test.ts tests/design-system-plan-gallery.test.ts tests/design-system-plan-confirm-integration.test.ts --no-file-parallelism` | 30 passed |
| 类型检查 | `cd core/ui && npx vue-tsc --noEmit` | 改动文件无错误；仓库存在与本次无关的 workflow 插件 rootDir 报错 |

## 6. 已知问题与未完成项

1. **既有失败：开工端到端的目标安装。** `core/tests/test_plan_execution_e2e.py::test_starting_a_ready_plan_installs_its_goal_and_steps_and_leaves_it_alone` 在最后一步断言 `goal` 记录时失败（`len(goals) == 0`）。已在 HEAD 基线的工作树复现（`git worktree add` + `PYTHONPATH` 指向基线源码），因此不是本次改动引入；读回方案、安装清单、投影清单三步都通过。需要单独排查 goal 工具在同一批 tool call 里的行为。
2. **真实模型行为未测。** `plan-docs` 的 8 条评测与三个旧技能的 24 条评测都只做接线校验（`status: NOT_RUN`）；需要在配置生产模型的运行器里逐条跑，才能声称「按类型写得好」。
3. **导出未做真实点击。** 导出走浏览器下载（`Blob` + `a.download`），单测只验证按钮与事件；桌面 WebView 的保存落点需要现场确认。
4. **历史方案 18 份未分类。** 按 PRD「保留无法自动判断的历史方案」，只给出建议，没有批量写入类型。
5. **方案与项目的关系由位置表达。** 没有在 frontmatter 增写「项目」字段；跨项目发起任务时用绝对路径和访问批准说明。这是对「优先复用现有能力」的取舍。
6. **修改理由没有独立版本引擎。** 依赖 Git 提交与方案正文的「差异」小节；没有实现自动历史快照。

## 7. 与 PRD 的偏差

| 偏差 | 原因 |
| --- | --- |
| 新建时的类型由用户选（可留空），没有提供每种类型的独立表单 | 最小必要复杂度；类型决定骨架，正文由 Agent 在对话中写 |
| 归档不单独建动作，用设计状态「已归档」表达 | 避免多一套状态机；文件仍在原位，符合「不擅自移动历史文件」 |
| 关联只记录文档路径与会话 id，不做关系数据库 | PRD §10.2 明确允许用轻量元数据 |
| 类型推断只做读侧，不回写 | PRD §6.5「不要求批量重写历史方案」 |

## 8. 下一步建议

1. 用生产模型跑 `plan-docs` 与三个旧技能的 32 条评测，把 NOT_RUN 换成真实输出。
2. 单独排查 goal 工具的批量调用失败，恢复端到端用例。
3. 现场确认桌面导出的保存路径；如需「另存为」对话框，再补桌面能力。
4. 让用户逐份确认历史方案的类型与专题，优先处理报告里的 18 份未分类。
