---
name: curate-notes
description: 在 Study 中把可信原始快照整理为可追溯的 Resource，并维护由多份 Markdown 文档组成的用户知识库 Note。用于整理、连接或修订笔记；不把阅读或标记当作掌握证据。
metadata:
  version: "4.0.0"
  study-stage: "active"
---

# Study 三层笔记维护

本技能只保留会改变决策的约束；具体字段和动作见[三层笔记参考](references/notes.md)。

## 1. 三层模型

- **Raw**：宿主从会话、标记、考试和知识节点捕获的原始快照。它是只读事实，Agent 只能读取，不能创建、改写、补造或把推测写回 Raw。
- **Resource**：Agent 根据 Raw 生成的、可版本化的素材。每个 Resource 必须引用真实 `raw_ids`，保留来源链和版本；它供 Note 使用，不是用户点击后看到的最终笔记，也不能冒充用户原文。
- **Note**：用户知识库中的真实 Markdown 文档。Note 以文件路径和全文 Markdown 为真源，可有父文档、`[[note:<id>]]`/`[[node:<id>]]` 链接、反向链接和 Markdown 原生语法。每篇 Note 必须引用至少一个真实 Resource；frontmatter、来源脚注/尾注和索引字段由宿主管理。

## 2. 开始前先读

1. 先加载本技能，再按请求范围读取 Raw、相关 Resource 和目标 Note；没有明确 Note 时用 `tree`/`list` 找候选，按分页继续读取，不扫描无关会话。
2. 先确认可复用的 Resource 与 Note，记录各自 revision/hash 和真实来源。不要因为看过内容、收到标记、读过 Note 或生成过自测题就推断掌握。
3. 只从 Raw 中得到个人事实；模型讲解、外部资料和用户原话要分别标明性质。来源缺失、冲突或过期时写待确认，不编造 ID、题号或结论。

## 3. 最小增量维护

- 先更新/创建 Resource，再引用 Resource 更新/创建 Note；不要把 Resource 直接当成 Note 展示给用户。
- Resource 写入使用 `resource_create`/`resource_update`，保留真实 `raw_ids` 和当前 `expected_revision`。Note 写入使用 `create`/`update`，保留真实 `resource_ids`、当前 Note revision、`expected_content_hash` 和完整 `body_md`。
- Note 是全文 Markdown：保留公式、代码、列表、引用和用户排版；不要改写用户未请求的内容，不要手写或覆盖宿主管理的 frontmatter/来源尾部。
- 用 `[[note:<真实 ID>]]`、`[[node:<真实 ID>]]` 消歧；链接放在正文语义需要的位置。`graph` 是当前 Note 的关系视图，显示在 Note 右侧栏，不是新的知识层或后台任务。
- 用户进入 Note 后，通过 Notes 对话请求 Agent 维护当前文档；没有成功回执和目标 revision/hash，不得声称已保存。

## 4. 用户保护与冲突

- 用户可在 UI 框选并锁定范围；锁定只阻止 Agent，不阻止用户继续编辑。Agent 不调用锁定/解锁动作，也不伪造锁状态。
- `NOTE_REGION_LOCKED` 时必须保留未保存草稿，回报 `reason` 与 `overlap`/重合范围，改为建议或请求用户决定；不得绕过、切碎重合范围、静默覆盖或另造等价 Note。
- `REVISION_CONFLICT`、`CONTENT_HASH_CONFLICT` 或外部 Markdown 变化时，重新读取 Raw/Resource/Note，比较当前内容后做最小变更；不盲目重试。
- 只有工具明确成功且回执目标、revision/hash 与本次变更一致时，才能说已创建或更新；失败、超时和状态不明均按未保存处理。

## 5. 来源与表达底线

引用用户原话时保留原文并明确它是引文；不要把 AI 改写冒充用户内容。个人误区只能写到证据支持的强度；考试结论仍由考试流程产生。整理行为本身不产生掌握、通过或长期记忆。

需要动作字段、Markdown 文件约定、错误回执和示例时，读取[三层笔记参考](references/notes.md)；需要外部资料检索边界时，再读取[资料与工具决策](references/resources.md)。
