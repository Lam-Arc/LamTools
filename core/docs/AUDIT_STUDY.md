# Study v2 现场审计

审计日期：2026-09-18  
审计基线：`56d45e4e9257ec1be9c98a948783b23ff598183d`（`codex/multiplatform-dev`）  
设计输入：`Study_完整设计与执行包_v2.0.zip` 的 README 与 `docs/01`—`docs/04`；包内参考代码仅作合同参考，不作为仓库事实。

> 历史审计说明（2026-09-20）：本文主体保留 2026-09-18 的现场基线，不能用来描述
> 当前实现状态。原“笔记”缺口与 P3b Note/NoteBlock 方案已被部署
> `study_notes_three_layer_20260920` 的 Raw → Resource → Note 实现取代；旧 NoteBlock
> 仅保留为兼容迁移输入，不是运行时笔记合同。当前实现与验证结论见本文末的 closure note。

## 1. 工作区与数据保护

- 审计开始时工作区已有大量未提交修改；Study 后端、前端和测试多数仍是未跟踪文件。所有现状结论均针对“上述提交 + 当前工作树”，不能归因于提交本身。
- 未执行 reset、checkout、clean、删库、推送或发布，也未覆盖用户文件。
- 已用 SQLite `.backup` 将 `core/data/core.db` 与 `core/core.db` 备份到 `E:\LamTools\.tmp\study-v2-backup-20260918-0158`；两个副本 `PRAGMA integrity_check` 均为 `ok`。
- 审计时没有找到现存 `study.db`，因此不存在可直接演练的真实旧 Study 库；迁移代码必须先在合成旧库和备份副本上重复运行，再允许接触未来真实库。
- Python 运行时 SQLite 为 3.50.4，备份 CLI 为 3.50.6；均低于设计附件所述 WAL 修复版本 3.51.3。Core 连接启用 WAL/NORMAL/busy_timeout，但未逐连接启用 `foreign_keys`；当前 StudyStore 连这些 PRAGMA 也没有。

## 2. 审计矩阵

| 项目 | 现有证据 | 缺口 | 决策 | 影响 | 验证办法 |
| --- | --- | --- | --- | --- | --- |
| 模式与 Agent Loop | `app/base_agent.py:CoreBaseAgentKit.build_model_request` 在 `study:study` 下替换业务身份，但复用同一 Kernel、工具、权限和流式协议；`plugins/bundled/study/plugin.json` 注册现有模式。 | 无 Study 用户/环境 scope；Study 当前跳过所有 ProjectContext，包括全局记忆。 | **扩展**现有 profile/context provider；不建第二套 Agent Loop。 | 运行中 mode/session/context 必须冻结，Study 不再依赖 project。 | Study/Agent/Workflow 提示隔离、取消、流式、附件和回归测试。 |
| 会话与消息 | `study/backend.py:ensure_study_session` 复用 `CoreDbSessionStore`；已有 `study:main` 和确定性 `study:node:*`，消息仍在 Core 表。 | UI 和 `study.current` 固化单 `study:main`；没有 map/notes/node binding、当前 primary 唯一约束、replace-primary、持久草稿。 | **扩展**宿主会话绑定；**局部重构** Study 当前节点路径。 | 同节点跨课程共享主会话；旧会话、消息和附件必须保留。 | G01/G03、并发 ensure、replace-primary、草稿不覆盖、回访不重复预填。 |
| Study scope / ACL | `PluginContext` 提供服务、数据目录和 metadata；Core 有 workspace identity。 | StudyStore 所有 key 全局共享；没有可信 principal/user/environment/library，payload 也没有真正 ACL。 | **新增最小 Scope/Principal 合同**，由宿主注入而非模型声明。 | 未完成前不能宣称多用户安全。 | 正例 + 跨用户、跨环境、伪造 payload、跨库 request_id 反例。 |
| 知识主数据 | `StudyStore.build` 有单批事务、全局 revision、1–100 操作、失败回滚、重复检查；稳定 node ID、多课程/模块归属、内容和来源占位已存在。 | JSON 大表无 typed FK/实体 revision/软删；contains 与 course_ids/module_ids 双主；contains/prerequisite/advanced 混成一张 DAG；没有 learnable、progress_role、coverage manifest、backlink/redirect 完整影响清单。 | **局部重构**为唯一事务写源；保留 SQLite，不引图数据库。 | 需要兼容读取旧实体并迁移，禁止直接硬拆旧记录。 | G01/G04—G10、contains 与 prerequisite 分别检环、related 环允许、共享节点删除不误删。 |
| 读取/写入合同 | `get_knowledge_net` / `build_knowledge_net` 是真实工具 ID；当前有分页、批写和结果体限制。 | 读默认/上限为 50/100、250 KiB；写为 250 KiB；offset 游标不绑定 scope/revision；无 per-entity CAS、request receipt。 | **扩展原工具**，不注册同义工具。 | 模型/UI 预算应分离；结构和掌握 revision 分开。 | 默认20/最大50/32 KiB、写128 KiB、STALE_CURSOR、同键同请求/不同请求、越权先于 receipt。 |
| 权限/审批 | 工具清单和宿主 `ApprovalGate` 已存在；插件工具沿用 Tool Gateway。 | Study 工具和 RPC 全部 `auto_allow`；operation 执行期没有 Study action policy；历史删除只接收 `confirm_history` 布尔。 | **扩展**现有网关 action policy 与审批 continuation。 | build/sign/exam/reveal/delete/merge/notes/memory 必须由代码校验。 | 允许/拒绝/审批续接/注入文本不能提权测试。 |
| 幂等、事件、任务 | Core 有 revision CAS 与 Arrange 任务/lease/recovery；Study sign 对同一评分版本有部分幂等。 | Study 无通用 receipt/outbox；提交后再 broadcast 有崩溃窗口；Arrange 没有 fencing/checkpoint 且 Study 未接入。 | **新增** Study receipt/outbox；**扩展** Arrange，不建第二个 scheduler。 | 长任务可取消/恢复，过期 worker 不得提交。 | 故障注入 5.1—5.7、重复事件消费、stale fencing、重启恢复。 |
| 技能与提示词 | 四技能通过现有 SkillRegistry/`load_skill` 仅在 `study:study` 可见；`study-system.md` 已替代通用业务提示词。 | v2 正文与旧包需做内容差异更新；`curate-notes` 只能到 P3b 注册。 | **直接复用并更新正文**。 | 四技能正文仍按需加载，不能常驻。 | Study 可见/Agent 不可见、load 正文、P3b 前后 curate-notes 可见性。 |
| 模型网关 | QuickAssist/出卷/评分使用同一 `context.llm_client`、`tools=[]` 和独立提示，不进入主 Agent Loop。 | 直接 `.complete()` 绕过 `complete_with_retry`、统一取消、用量/事件标签和 durable task。 | **扩展宿主 Direct ModelGateway**。 | 不重造模型池；隔离答案仍需程序白名单。 | 模型路由/限流/取消/用量标签、无工具、私有材料不进入主历史。 |
| 考试与 sign | 公开试卷和 `exam_private` 已分离；保存草稿不等于提交；整卷批改、帮助、uncertain、review、sign 证据匹配已有测试。 | 无 submission CAS/冻结版本/resubmit；results 可由调用方传入；同表无 capability ACL；图片引用未校验；无 needs_review、规则/模型版本；仍用 60/80/100 比例，fail 仍携带 mastery。 | **局部重构**现有 exam/sign，不增加同义工具。 | 权限、泄题和错误掌握回写为发布阻断。 | E01—E10、H02、多图不清、复核替代、受助不升级、fail mastery=null。 |
| 标记与 QuickAssist | 全局 ContextMenu、SelectionAssistant、MarksPanel、词典优先、per-mark 小线程和唯一重定位已有实现；右栏原文/图标行为已区分。 | 缺显式纯标记菜单；锚点持久化为 UTF-16，无 source revision/projection/fragments；全量加载 marks；没有真实取消、移动长按和完整键盘焦点。 | **扩展**现有组件与 `study.text/marks`；不重做 UI。 | 纯标记和词典命中必须 0 模型；标记不是掌握证据。 | A01—A07、emoji/组合字符/公式/跨块、过期响应、触屏/键盘。 |
| 搜索与置顶 | 宿主已有 SearchShell、SessionSidebar 和稳定 session ID；Study 会话可进入现有会话搜索。 | 无 Study entity provider；节点/笔记不可搜；置顶仅项目/会话 localStorage，无 scoped entity pin。 | **扩展**宿主 provider/pin store，复用现有 UI。 | 命中 Study 实体需切模式并按权限定位。 | 节点/笔记/会话搜索，重命名后 pin 保持，跨环境不可见。 |
| 图谱与树 UI | StudyView 复用 VueFlow、主题、viewport/position、分页、关系图例和邻接检查。 | Sidebar 只有学习/总览/课程，课程点击直接进网图；entity 类型代替 learnable；返回固定 chat；主线程 O(n²) 力布局；无 notes/map 双管理会话。 | **局部重构页面状态和树行**，保留组件和样式体系。 | 左栏应为总览/图谱/笔记/学科树；图只显示局部。 | G02、200/600 局部图、返回来源、树路径实例、多父节点、准确名称。 |
| 掌握状态 UI | 当前 Circle/Check 和红黄绿 token 可复用，已有 aria-label。 | DTO 只有 passed/mastery，无法区分 unassessed/fail 的可访问文本；无触屏详情。 | **扩展状态 DTO/helper**。 | 视觉仍同灰色未完成，但语义必须不同；学习位置/覆盖/掌握分离。 | title/aria/触屏、色弱非颜色信息、aggregate 不自动勾选。 |
| Dreaming/Memory | `MemoryEntry/MemoryQuery`、SQLite store、Dreaming 抽取/去重、Kernel stop hook 和 `MEMORY.md` 合并骨架可复用；95 个 Study/Memory/Dreaming/Arrange 聚焦测试通过。 | 去重查询不按 work_root；Study 可能写项目 MEMORY.md，Study prompt又不读它；无 scope/source status/version/correct/forget/suppression；失败吞掉、无 durable job。`session_id`/`thread_id` metadata 也不一致。 | **局部重构边界、扩展服务**；不因文本存储整体推倒。 | 先接最小 scoped read/explicit remember，再在 P3a 加整理/纠正/遗忘/恢复。 | M01—M05，至少 Study + Agent 双场景，忘记后缓存/派生不复活。 |
| 笔记（历史基线，已 superseded） | 审计时现有 node/course/module `notes` 仅是短字符串；Markdown renderer 可复用。 | 审计时缺 Note/NoteBlock、来源/修订/锁/反链/冲突处理/管理会话。 | **历史建议：新增 NoteService；已由三层 Markdown vault 实现替代**。 | 旧行只描述 2026-09-18 缺口；不作为当前运行时合同。 | 当前证据见本文末 closure note。 |
| SQLite | Core 有单写协调、WAL/NORMAL/busy_timeout；Study 有短事务。 | 运行时版本低于附件要求；foreign_keys 未逐连接开启；Study 读取也 `BEGIN IMMEDIATE`，没有受支持的独立备份入口。 | **扩展连接配置和备份/迁移检查**。 | 在引擎升级前只能记录残余风险，不能宣称满足 WAL 修复要求。 | 每连接 PRAGMA、integrity/FK check、WAL 备份、busy/磁盘满故障。 |
| P4/P5 | 节点已有 `sources` 占位，标记有 source/page/rects，附件沿用 Core。 | 无教材、PDF、知识库文件解析、RAG、向量库、适应性学习。 | **不做实现，仅保留接口**。 | 禁止把占位字段说成已建资料系统。 | schema/DTO 兼容性检查；功能标记为 unavailable。 |

## 3. 已运行的 P0 证据

- 后端现场聚焦：`tests/test_study.py tests/test_memory_store.py tests/test_dreaming.py tests/test_arrange_runtime.py`，`95 passed`。
- 前端现场聚焦：Study、mode、plugin host、session sidebar、Markdown code/table，`47 passed`。
- LamTools 设计审计：84 个文件，0 项新偏差。
- 这些结果只证明旧合同基线，不证明 v2 新合同、真实模型、Tauri、迁移或性能已通过。

## 4. 分阶段适配边界

1. **P0**：可信 StudyScope、action policy、DB schema/migration/backup、receipt/outbox、消除全局 current；在副本重复迁移并输出核验。
2. **P1**：唯一知识写源、typed relation/coverage、map/notes/node SessionBinding、会话草稿、v2 exam/evidence/sign、Direct ModelGateway、Arrange fencing/checkpoint、树/局部图/状态 DTO。
3. **P2**：纯标记、code-point 锚点、source revision/fragments、QuickAssist 取消/用量、Study 搜索与 scoped pins、触屏/键盘补齐。
4. **P3a**：MemoryService scope/source/status/version/explicit remember/correct/forget + Dreaming durable consolidation，Study 与非 Study 共同验证。
5. **P3b（历史计划，已 superseded）**：原计划为 Note/NoteBlock、锁、来源、修订、
   双链、notes 管理会话与按需 `curate-notes`；当前已改为 Raw → Resource → Note、
   真实 Markdown vault、全文 CAS、UTF-16 用户锁和 Note-only 右栏关系图。
6. **P4/P5**：保持未实现，只保留资源/来源/provider/evidence 边界。

任一阶段若出现数据不可恢复、权限绕过、泄题、错误归属、静默覆盖或错误掌握回写，即停在该稳定边界，不以“清单完成”代替真实证据。

## 5. 2026-09-20 closure note：三层笔记部署

当前 Note 实现由可信宿主捕获不可变 Raw（会话、标记、考试、节点），由 Agent 以
真实 `raw_ids` 生成可版本化 Resource，再由用户或 Agent 通过 CAS 维护真实 `.md`
文件组成的 Note 知识库。每篇 Note 必须引用 Resource；正文真源是 scope vault 中的
UTF-8 Markdown 文件，SQLite 只保存索引、关系、来源、版本和锁。文件树由 `path`
决定，`parent_id` 仅表示语义父文档。来源在文末以低调的论文式行展示。

Note 工作区进入后左栏变为 Markdown 文件树，顶部提供返回和 Notes 对话；Note-only
总体关系图位于右栏，只绘制 Note 间 wikilink/父子边。用户可以框选并以 UTF-16 code
unit 锁定范围；锁只阻止 Agent，冲突返回 `NOTE_REGION_LOCKED`、原因和重合区域，
用户编辑仍可继续。外部文件变化、revision 或 hash 不一致时，Agent 不覆盖新内容。

Closure evidence：Study 后端聚焦套件 66 passed（另有 2 个 SQLite datetime
deprecation warnings）；Study 前端 31 passed；`npm run typecheck`、`npm run build`、
Study compileall、`curate-notes` quick validation（UTF-8）通过；LamTools 设计审计
85 files / 0 deviations；独立 Tester PASS。构建仅保留既有 `::highlight` 与
ineffective dynamic-import warnings。未执行 Tauri/Computer Use 手工验收、完整全仓库
回归、真实模型语义验收或真实用户库迁移。
