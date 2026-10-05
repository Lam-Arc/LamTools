# Study：知识库、节点会话、考试、标记与三层笔记

本文是当前仓库实现的模块说明，不是设计包的原样复制。三层笔记部署
`study_notes_three_layer_20260920` 已完成；P4 教材/PDF/知识库/RAG 和 P5 远期能力
仍只保留接口。

## 架构与范围

Study 复用 Core 的 Agent Loop、Kernel、Tool Gateway、权限/安全协议、模型路由、
流式响应、取消、限流和会话/消息/附件持久化。Study 是 project-independent 模式，
但数据由宿主可信 metadata 提供的 `(user_id, environment_id, library_id)` 精确
隔离；没有完整可信身份时仅使用显式标记的本地兼容 scope。模型或普通 payload
不能声明或覆盖 scope。

入口位于 `core/src/lamtools_core/plugins/bundled/study/`，前端位于
`core/ui/src/study/`。左栏提供搜索、总览、图谱、笔记、置顶和懒加载学科树；
课程/分组只展开，不直接创建会话。知识图谱使用现有 VueFlow 做局部、分层、可保存
视口/位置的关系图。进入 Note 后，左栏切换为 Markdown 文件树，顶部提供返回和
Notes 对话；Note 的总体关系图归属 Note，显示在右侧栏，只展示 Note 间的 wikilink
与父子关系。既有 Core 聊天组件继续负责消息、草稿、附件、分页和流式显示。

## 工具、技能与提示词

既有工具 ID 不变：

- `get_knowledge_net` → `study.get`
- `build_knowledge_net` → `study.build`
- `exam` → `study.exam`
- `sign` → `study.sign`
- `notes` → `study.notes`（仅在 Study 可见，保持每轮工具集稳定）

五个请求技能 `build-map`、`teach`、`answer`、`take-exam`、`curate-notes` 由现有
`SkillRegistry`/`load_skill` 按需加载，只有 active mode `study:study` 可见。
`teach` 是教学技能组（teaching group）的入口：它持有目标、来源、图示、密度、
反馈与发送前检查的共同协议，并按学科加载成员技能——`teach-humanities`（历史、
哲学、文学、宗教、法律、政治、伦理、艺术与文化解释）或 `teach-science`（数学、
物理、化学、生物、统计、计算机、电子与工程）。两个成员在 `agents/openai.yaml`
声明 `allow_implicit_invocation: false`，只由入口按名加载，因此技能索引里只有入口；
成员把硬性要求叠加在共同协议之上：文科必须先讲一个具体寓言承载道理，再命名道理
并逐项映射、说明故事边界；理科必须在每个定义、公式或定理之后立刻给出"正常人能
直接体会或理解"的释义，再进入推导。成员不新增工具权限，也不替代入口协议。
Study 会话自动加入 `prompts/study-system.md`，公共安全、权限、工具和验证协议
仍来自宿主；普通 Agent 的项目/业务提示词不会注入 Study。`notes` 使用当前
`study.notes` 三层 RPC/存储合同并在 Study 工具集中保持稳定，`curate-notes` 正文
仍按需加载；Agent 不能覆盖用户锁定的 Note 范围。

## 三层笔记架构

笔记数据按 Raw → Resource → Note 分层。三层不是同一种“块”，只有 Note 是用户
点击后看到的最终知识库。

### Raw：不可变原始快照

Raw 由可信宿主从 Study 会话消息、标记、考试和知识节点幂等捕获，保存原文、来源
类型、来源 ID 和 metadata。Raw 是事实快照：Agent 只能读取，不能创建、改写、补造，
也不能把推测写回 Raw。`raw_list` 读取前会同步宿主可见的候选来源，`raw_get` 读取
单条快照；读取支持分页。

### Resource：AI 的可追溯素材

Resource 是 Agent 读取真实 Raw 后生成的 AI 笔记素材，不是最终笔记展示。每个
Resource 必须引用至少一个真实 `raw_id`，写入只能经过可信 Agent 路径；更新使用
`expected_revision`，每次版本保留在不可变 Resource history 中。Resource 可以被
Note 引用，但不能冒充用户原话、掌握证据或最终 Note。

### Note：真实 Markdown 知识库

Note 的正文真源是 scope 对应 vault 中的真实 `.md` 文件，SQLite 只保存索引、路径、
关系、Resource 关联、revision、hash 和锁。应用数据目录下的 vault 由 scope 派生，
写文件采用临时文件加原子替换；frontmatter 和文末来源区由宿主管理，正文保持完整
Markdown，不将正文拆成旧式 NoteBlock 卡片。

每个 Note 必须至少引用一个真实 Resource。文件包含可读的低调来源行（论文式参考文献
风格）和宿主哨兵；来源标题与 ID 会做 Markdown/URL 安全转义。正文可使用 Markdown
原生结构，包括标题、列表、引用、表格、代码、公式、Mermaid 和 Callout；
`[[note:<真实 ID>]]`、`[[node:<真实 ID>]]` 可建立 Note 或知识节点链接，未解析链接
保留且不阻止保存。Note 读取时派生链接和反向链接，避免单独链接表与 Markdown 漂移。

`path` 只决定 vault 的物理文件树位置；左栏目录中的 folder 节点由路径生成，Note
文件是可点击叶节点。`parent_id` 只表示 Note 的语义父文档关系，用于 Note 关系图，
不会把语义父子关系伪装成文件夹。

## Note 编辑、锁与一致性

用户和 Agent 都可以维护 Note 的完整 Markdown 正文。Agent 维护时必须先读取 Raw、
相关 Resource 和目标 Note，再以最小增量提交，并携带当前 Note `revision` 与正文
`content_hash`；Resource 写入同样使用 revision CAS。Agent 遇到版本/hash 冲突或
真实 `.md` 被外部修改时必须重新读取，不覆盖较新的内容。用户读取外部修改后的
准确 hash 后可以接纳该编辑并继续保存。

用户可在编辑器或预览中框选文本，右键锁定该范围。锁的偏移单位是 UTF-16 code unit，
锁定只阻止 Agent，不阻止用户；用户编辑后系统会尝试重新锚定锁，无法可靠定位时保守
标为 orphaned。Agent 修改若与 active/orphaned 锁重合，操作返回结构化
`NOTE_REGION_LOCKED`、`reason` 和 `overlaps`，前端保留未保存草稿并展示重合区域；
Agent 不得绕过、切碎或伪造锁。只有用户可以锁定或解锁。

进入 Note 后，用户通过顶部“对话”打开独立的 Notes 会话，请 Agent 读取、整理、连接
或修订当前 Note；新建 Note 也从 Notes 对话开始，以确保先获得可引用的 Resource。

## 数据、迁移与一致性

`StudyStore` 是知识层和 Study 辅助数据的唯一事务写源；Markdown 是内容/导出
表示，不另建图数据库、向量库或文件/数据库双主。运行时在应用数据目录创建
`study.db`，包含：

- scope 记录、结构/状态 revision、绑定 scope 的游标、request/sign 回执和事务
  outbox；
- 稳定节点身份、多课程/模块归属、`learnable`/`progress_role`、typed relation、
  软删除快照、合并 alias 和分别检查的 `contains`/`prerequisite` DAG；`related`
  允许环；
- `map`、`notes`、每个可学习节点各一个 primary `SessionBinding`。安全旧节点 ID
  保持可读，Unicode/标点 ID 使用稳定 hash；首次空草稿只预填学习句，不自动发送、
  不覆盖已有草稿；
- Raw 快照、版本化 Resource、真实 Markdown Note、来源引用、revision/hash、UTF-16
  用户锁定范围、wikilink/父子关系和反链；搜索与置顶按 Study scope 保存；
- 考试草稿、公开试卷、持久化参考答案/评分标准、整卷提交/批改、帮助记录、逐题
  得分证据、review 历史和幂等成绩回写。普通读取不包含参考答案或 rubric；当前
  Agent 在上下文已缺失判卷依据时通过显式 `reference` 动作按需读取。

首次打开会幂等创建 Study 表，把旧结构复制进显式的 local compatibility scope；历史
`study_note_blocks` 只作为一次性兼容迁移输入，不是当前 Note 读写合同。不会删除旧
消息、标记、笔记或考试记录。真正用户库迁移前应先执行 SQLite `.backup`，保留原库，
完成 integrity/FK 检查并在副本重复迁移。当前三层部署没有宣称真实用户库迁移验收。

已保存的审计备份：
`E:\LamTools\.tmp\study-v2-backup-20260918-0158`，对应
`core/data/core.db` 与 `core/core.db`；两者 `integrity_check=ok`。

## 考试与掌握

`exam` 的正常流程是当前 Agent 用 `create` 一次保存整卷、每题分值、参考答案和
评分标准→保存答案草稿→显式 `submit`→当前 Agent 用 `grade`/`review` 保存逐题
得分、步骤反馈和证据。判卷不再触发第二个隔离模型，也不对选择题答案做原始字符串
严格比较；程序只校验结构、分数范围、版本和证据归属。选择题、问答和图片引用沿用
Core 附件；帮助、不确定、图片不可读的题目不能作为独立通过证据。`sign` 只接受当前
`grading_version`、精确 question IDs 和已保存的有效证据；review 替换当前证据
但保留历史，不增加独立考试计数。未评估/未过是中性未完成状态；通过按低/中/高
显示红/黄/绿勾，并提供可访问文本。学习位置、建图覆盖和掌握状态分开保存。

当前仍缺少 action 级 Study approval/policy 的完整代码边界；工具声明仍为
`auto_allow`，不能把提示词中的权限规则当作已完成的安全控制。

## 标记、轻量询问与记忆

`study.marks`/`study.text` 复用现有 ContextMenu、SelectionAssistant 和
MarksPanel。纯标记不调用模型；词典优先，未知词/短语再走模型回退；解释、翻译、
询问使用独立短上下文和选文锚点，不进入主 Agent Loop。锚点保存 Unicode
code-point 单位、来源 revision/fragments，原文改变且无法唯一重定位时明确提示，
不跳到任意重复文本。标记是关注记录，不是掌握或能力证据。

`mem/` 中的 `MemoryScope`、`MemoryService`、来源/状态/version、显式 remember、
correct/forget/suppression 与 Dreaming 整理接口共用全局 Memory 服务。教学提示
留在知识数据，个人长期特点才进入 scoped shared Memory；单次错误、标记或考试
不会自动推断全局能力/敏感身份。当前轻量 Study 调用仍直接使用 context LLM
client，尚未统一到要求中的 Direct ModelGateway retry/cancel/usage 管线。考试
出题与判卷复用主 Agent Loop，不另建模型调用。Dreaming 的完整后台 durable
recovery/整理仍是后续工作。

## CLI 与运行

所有 GUI 能力通过同一 RPC，并由 Study CLI 暴露：

```powershell
cd E:\LamTools\core
py -3.14 -m lamtools_core.cli study context --params '{}'
py -3.14 -m lamtools_core.cli study session --params '{"scope":"map"}'
py -3.14 -m lamtools_core.cli study get --params '{}'
py -3.14 -m lamtools_core.cli study build --from-file patch.json
py -3.14 -m lamtools_core.cli study exam --from-file exam.json
py -3.14 -m lamtools_core.cli study sign --from-file sign.json
py -3.14 -m lamtools_core.cli study marks --params '{"action":"list"}'
py -3.14 -m lamtools_core.cli study notes --params '{"action":"raw_list"}'
py -3.14 -m lamtools_core.cli study notes --params '{"action":"resource_list"}'
py -3.14 -m lamtools_core.cli study notes --params '{"action":"tree"}'
py -3.14 -m lamtools_core.cli study notes --params '{"action":"graph"}'
py -3.14 -m lamtools_core.cli study notes --params '{"action":"get","note_id":"<id>"}'
```

连接 Tauri/HTTP Core 时按现有方式附加 `--base-url` 与 `--token`（或
`LAMTOOLS_CORE_API_URL`/`LAMTOOLS_CORE_TOKEN`）；CLI/RPC 不创建第二套会话或
模型网关。

## 验证与未执行项

三层笔记部署的验证结果：Study 后端聚焦套件 `66 passed`，另有 2 个 SQLite datetime
deprecation warnings；Study 前端聚焦套件 `31 passed`；`npm run typecheck`、
`npm run build`、Study `compileall` 通过；`curate-notes` quick validation 通过
（UTF-8）；LamTools 设计审计为 85 files / 0 deviations；独立 Tester 结论为 PASS。
构建只保留既有 `::highlight` 与 ineffective dynamic-import warnings。

本部署未执行 Computer Use/Tauri 手工视觉验收、完整全仓库回归、真实模型语义质量、
真实用户库迁移、打包、提交或发布。工作区仍可能包含并发/未跟踪修改，维护时应保留并
先进行用户要求的 Tauri 视觉验收，再考虑后续迁移或发布。
