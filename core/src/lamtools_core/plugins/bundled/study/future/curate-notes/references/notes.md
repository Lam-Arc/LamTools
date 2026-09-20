# 三层笔记参考

读取时机：需要调用 notes、组织 Markdown 知识库、处理来源/链接或解释写入冲突时。这里记录当前契约的非显然细节；技能入口只保留决策约束。

## 1. 数据归属

### Raw：宿主快照

Raw 是宿主从会话、用户标记、考试记录和知识节点捕获的原始快照。它包含 `raw_id`、`kind`、`origin_id`、原文 `content`、`metadata` 和捕获时间，并返回 `immutable: true`。Agent 只能用 `raw_list`、`raw_get` 读取；Raw 捕获属于可信宿主，不是 Agent 的写入能力。Raw 不存在时，先说明缺口，不用模型记忆或猜测补造。

### Resource：可追溯素材

Resource 是 Agent 读取 Raw 后生成的可版本化素材，包含 `resource_id`、`title`、`content`、`raw_ids`、`origin` 和 `revision`。创建或更新前确认 `raw_ids` 都是本次实际读取到的 Raw；没有来源的内容只能留在未保存草稿中。Resource 供 Note 组织和引用，不能作为用户点击 Note 后看到的最终呈现，也不能伪装成用户原文。

### Note：Markdown 知识库

Note 是用户可见的真实 Markdown 文件，SQLite 只保存索引、关系、revision/hash 和范围锁。一个 Study 笔记库可以有多篇 `.md` 文档；`path` 是库内相对路径，也是左侧文件目录的唯一结构来源；`parent_id` 只表达语义上的子文档关系，并生成 Note 关系图中的父子边，不改变文件目录。每篇文档必须有至少一个真实 `resource_ids`，宿主把来源写入 frontmatter，并在正文最下方按一行一条低调列出，呈现为类似论文参考文献的来源区；Agent 只提交正文、标题、父文档和来源 ID，不手写宿主管理字段。

正文可以使用 Markdown 原生语法，包括标题、列表、引用、代码围栏、表格、数学公式和图片。它不是旧式的拼接素材容器：Resource 应先被理解、去重和重组，再以完整文章写入 Note。用户内容、用户原话和 AI 整理内容要在语义上清楚区分；AI 改写不改变原文归属。

## 2. 读取顺序和动作

任何写入前都先按范围读取 Raw、Resource 和目标 Note。当前 notes 工具动作如下；参数以运行时 schema 为准，不从示例推测未声明字段。

| 动作 | 作用 | 关键输入/回执 |
| --- | --- | --- |
| `raw_list` | 分页前的 Raw 候选读取 | 可按宿主支持的范围筛选；返回 `raw_sources`，每条不可变 |
| `raw_get` | 读取完整 Raw | `raw_id`；返回 `raw`、`metadata` 和不可变标记 |
| `resource_list` | 找可复用素材 | 返回 Resource、`raw_ids` 和当前 `revision` |
| `resource_get` | 读取一条素材 | `resource_id`；返回完整内容、来源链和版本 |
| `resource_create` | 创建 AI 素材 | `title`、`content`、真实 `raw_ids`；回执 `resource_id`、`revision` |
| `resource_update` | 最小修订素材 | `resource_id`、`title`、`content`、`raw_ids`、当前 `expected_revision`；冲突不写入 |
| `list` | 查询 Note 候选 | `q`/`query`、`offset`、`limit`；返回标题、路径、Resource 引用、revision/hash |
| `tree` | 读取 Note 文件树 | 返回按真实 Markdown `path` 目录组织的 `tree`；`parent_id` 只表达子文档语义和图谱关系 |
| `get` | 读取完整 Note | `note_id`；返回 `body_md`、revision/hash、Resource 引用、链接、反向链接和锁定范围 |
| `graph` | 读取 Note 总体关系 | 返回当前 Note 库的节点/边；它是 Note 右侧栏视图，不是独立知识层 |
| `backlinks` | 读取反向链接 | `note_id`；只报告已解析的 Note 关系 |
| `create` | 创建 Markdown Note | `title`、`body_md`、至少一个真实 `resource_ids`，可选 `note_id`/`path`/`parent_id`；回执路径和 revision/hash |
| `update` | 原子更新 Markdown Note | `note_id`、完整 `body_md`、`resource_ids`、当前 `expected_revision` 和 `expected_content_hash`；成功才产生新版本 |

Raw 捕获、用户选区锁定/解除和宿主元数据维护不属于 Agent 的动作。Agent 不把锁状态、作者归属或来源尾部塞进正文参数。

## 3. 来源、链接和图谱

`Resource.raw_ids` 是 Resource 到 Raw 的来源链；`Note.resource_ids` 是 Note 到 Resource 的来源链。只使用实际返回的 ID；来源失效时保留“待确认”而不是换成近似 ID。外部网页或教材是外部补充，不能写成用户已经学会的事实。

Note 之间用 `[[note:<真实 Note ID>]]`，Note 指向知识节点用 `[[node:<真实节点 ID>]]`；目标唯一且已核实时才可使用普通 wikilink。链接应说明关系用途和边界，不能因为标题相似就批量堆叠。代码围栏、行式代码和数学内容中的文字不应被解析为关系。目标不存在或有歧义时返回待处理链接，不编造目标。

`parent_id` 只表达语义上的父子文档关系；它不决定左侧文件目录，不等于 wikilink，也不等于学习前置关系。关系图同时展示父子边和 Note wikilink 边，归属当前 Note 右侧栏。

## 4. 编辑、锁定与冲突

用户可以在 Note 编辑器中框选一段文字并锁定。锁定只是 Agent 写入保护，用户仍可自由编辑；用户编辑后宿主按引文、前后文和 revision 重锚范围。Agent 读取 `get` 时应保留锁定信息，但不尝试管理锁。

当 Agent 的完整正文变更与锁定范围重合，服务返回 `NOTE_REGION_LOCKED`，并尽可能带 `reason`、`overlaps`（或 `overlap`）及范围信息。必须保留本次未保存草稿，向用户说明冲突区域和原因，改为建议或请求用户处理；不得删去重合内容、拆分绕过、换写到另一篇等价 Note 或重试覆盖。

`REVISION_CONFLICT` 表示 Note/Resource 版本已变化；`CONTENT_HASH_CONFLICT` 或外部变化表示 Markdown 文件在读取后被改动。任何一种情况都要重新读取对应 Raw、Resource、Note，比较最新全文后做最小增量。超时或回执不明时先 `get`/`list` 判断是否已写入，再决定是否重试。

只有明确成功回执且目标 ID、revision/hash 与变更相符，才可向用户说“已创建/已更新”。否则写“草稿”“未保存”“冲突”或“服务不可用”，并说明可执行的下一步。

## 5. 组织示例与证据强度

可把一次答疑整理为：核心命题与条件、推导步骤、可复用例子、混淆点、与其他 Note 的真实连接。一次标记只能支持“关注”，一次翻译只能支持“已处理该内容”；只有实际考试证据或用户明确陈述才支持个人误区，而且措辞不能超过证据强度。

自检问题可以写进正文，但看过问题、读过答案、生成过 Resource 或整理过 Note 都不触发考试签名，不证明掌握。考试评定仍通过 exam 流程完成。
