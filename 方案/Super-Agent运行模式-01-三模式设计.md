---
状态: 草稿
摘要: consider/execute 换成 chat/work/auto（中文叫「智能」）三种会话模式；Super Agent 会话做 Router，把活派给带独立工作区的子代理
---

# Super Agent 作为第三种运行模式

## 需求与边界

- 复述：Super Agent 不是页面，也不是一个新工具，而是一种做事的方式，和「聊天」「工作」并列，在新建会话时选定，选完固定。按 DeepSeek Harness 的《Super-agent 设计探索》，选了这个模式的会话是 **Router**：它只和你对接，并尽量保持空闲；活派给子代理，派工时带一份六段式简报（工作范围可选，没有 git 也能派）；子代理干完汇报给 Router，Router 再回你。以前输入框里每轮都能切的 consider/execute 换成 chat/work/auto（智能），并且不再出现在输入框旁边。
- 完成后能看到：
  - 新建会话后，输入框上方是一个三选一的胶囊：聊天 / 工作 / Super Agent。发第一条消息时定下这条会话的模式，之后改不了，胶囊只显示当前模式。
  - 发过第一条消息之后，胶囊不能再改，只显示当前模式。
  - 在 Super Agent 会话里交一个目标：它派子代理去独立目录干，这条会话立刻还能继续用；子代理干完汇报回来，Router 再回复你。
  - 聊天只聊不改；工作当场做完。
- 这次不做：
  - 不做 Source / Trigger 自动接单（GitHub Issue、PR 评论、群聊消息自动建工单）。
  - 不做 Subscription，工单结束后不订阅原处，后续追问接不回同一件事。
  - 不做 observe 模式与准入表。
  - 不做人工验收关卡。原文没有这一环：执行器的最终报告就结束工单，成果的验收发生在 PR 的 review 与 merge 里。
  - 不做会话中途换模式。要换就新建一条。
  - 不做独立的 Super Agent 管理页面。
- 已定：旧会话没有「模式」这个概念，它们默认算「工作」。
- 假设：你以前如果自己调过每个模式能用哪些工具，改名时照旧名字换成新名字，你的工具清单本身不改。可以推翻。

## 取舍

- 选定：**人的注意力有极限，所以只留一个会话对人**，其余派出去。三种模式的差别是这条会话自己留下多少活：聊天一点不干，工作全干，Super Agent 只留对话、判断和派工。
- 选定：Router 与执行者分离。Router 不碰文件、不跑 shell，它只判断、派工、回话。这样一条长任务不会占住人的入口。
- 选定：执行者复用子代理，不新造 Worker。子代理已经有独立会话、持久记录、信箱、`recover`、`resume`、takeover 和 `clone_with_work_root`，缺的只是把工作区暴露到工具层。
- 选定：派工复用 `sub_agent` 加一个可选 `work_root`。空的 `work_root` 完全保持现有行为。这样工具面零新增。
- 选定：工单不建对象、不落库。它就是 Router 写给子代理的那段提示词，格式固定六段：工作范围（可选）、目标、上下文、任务、约束、验收标准、交付；目标那一段就是子代理的 goal。宿主只规定格式，不新增概念、不存工单表。
- 选定：模式是**会话的属性**，新建时写进会话，之后每轮读会话、不接受请求覆盖。这是「选好就不可变动」的落地方式。
- 选定：不做人工验收关卡。原文的工单只有 open 与 ended 两态，执行器报完即结束；人的结构化介入只有 stop 和回答提问。
- 被否：工单跑在发起它的那条对话里。主入口会被长任务占住。
- 被否：新增一个派工工具。和 `sub_agent` 职责重叠，多一个概念。
- 被否：保留输入框里的模式切换，只换名字。和「选好就不可变动」冲突。
- 被否：保留上一轮的独立面板。原文有面板，但只列等人处理的事；Sunday 已有的会话内决策卡已经承担这件事。

## 步骤

1. 模式注册表改名：`core/src/lamtools_core/tool/loadtools.py` 的 `default_load_tools()` 从 consider/execute 改为 chat/work/auto，三者说明文字写出行为差别。读旧配置时把 consider→chat、execute→work 映射过来，补上缺的 auto，保留用户自定义的工具清单。验证：新增用例断言默认三模式齐全、旧名字读进来变成新名字、自定义工具清单原样保留。
2. 模式集合与默认值：`core/src/lamtools_core/app/composer_state.py` 的 `COMPOSER_ACTIVE_MODES` 改为三元组，默认 `work`；`normalize_composer_active_mode` 接受旧名字并归一。验证：用例断言旧名字归一成新名字、非法值落到默认。
3. 模式在第一条消息时定下：`core/src/lamtools_core/app/live/turn_options.py` 里会话元数据的 `active_mode` 优先，一旦存在就忽略请求里传的值；不存在时把请求里的选择写进会话，请求里也没有就按「工作」补写（旧会话因此落到工作）。同时把 `active_mode` 从 `LIVE_COMPOSER_KEYS` 移出，堵住之后的热改；`session.composer.set` 这组参数完全不碰模式（点胶囊、改模型、改权限都不会提前锁死，模式只由第一条消息写入）。验证：用例断言「会话已定 chat，请求传 auto，仍是 chat 且不写库」「空会话首次带 auto，落库为 auto」「什么都不带时落库为 work」「旧名字 consider 落库为 chat」。
4. 辅助会话固定为 chat：`core/src/lamtools_core/app/auxiliary_chat.py` 与 `core/src/lamtools_core/tool/default_toolbox.py` 里写死的 consider 改为 chat。验证：`core/tests/test_auxiliary_main_chat.py` 更新后通过。
5. `sub_agent` 加可选 `work_root`：`core/src/lamtools_core/agent.py` 的 `SUB_AGENT_TOOL_SPEC` 增加 `work_root`，只进 `properties` 不进 `required`；`core/src/lamtools_core/tool/default_toolbox.py` 的 `call_sub_agent` 用它配 `clone_with_work_root`。验证：用例断言不传时子代理目录等于父会话目录，传了则等于指定目录。
6. 派工简报进提示词：新增 `core/src/lamtools_core/app/superagent_brief.py` 的六段格式，只在 Super Agent 模式下随运行时上下文给出；`core/src/lamtools_core/app/base_agent.py` 把它排在模式行之后。工作范围一段可选，写不写都能派工。验证：用例断言六个段落齐全、目标段声明为子代理的 goal、工作范围留空即用当前项目目录且不要求 git、其它模式不出现这段。
7. 子代理结束汇报回主入口：子代理结束后把它的最终报告作为一条消息回到发起它的会话，复用现有的成员完成事件与持久化，Router 据此回复用户。验证：用例断言发起会话里出现一条带子代理名的汇报，且这条汇报写失败不影响子代理本身的结果。
8. 界面改造：在输入框上方加一个三选一胶囊（聊天 / 工作 / Super Agent），只在会话还没有消息时可点；发过第一条消息后它变成只读的模式标识。发送时把选择带进这一轮请求。删除 `core/ui/src/components/CoreSuperAgentPanel.vue` 及左侧导航、页面注册、分屏菜单与绑定。验证：`vue-tsc` 无新增错误；空会话里胶囊可点，发过消息后点不动；左侧导航不再有 Super-agent 一项。
9. 端到端走一遍：新建 Super Agent 会话，交一个复杂目标，确认派工后主入口仍能对话、子代理在自己的目录里干、结束后汇报回到主入口；再新建一条聊天会话，确认它不改文件。验证：两段真实对话记录，加子代理目录。

## 目标与完成判据

- 目标：让「用 Super Agent」变成选一条会话。这条会话是人的唯一入口，不会被长任务占住，活都在带独立工作区的子代理里干完再回来。
- 判据：
  1. 新建会话后，输入框上方是一个三选一胶囊；发送第一条消息时定下这条会话的模式，之后胶囊只显示当前模式、点不动。
  2. 输入框旁不再有每轮可切的模式切换。
  3. 聊天不改文件；工作当场做完；Super Agent 派子代理到独立工作区，主入口在子代理运行期间仍可用。
  4. 子代理结束后汇报回到主入口会话。
  5. 左侧导航不再有独立的 Super-agent 页面。
  6. 旧的 consider/execute 配置与会话仍可用，落到 chat/work。
  7. 同一件事，用 Super Agent 要你交代的轮次和盯的环节明显少于工作模式。
  8. 新增用例通过，界面类型检查无新增错误。

## 风险

- 把汇报写进来源会话 — 中等 — 只复用现有持久化与推送，写入失败不能让子代理的工作判失败。
- 主入口与子代理同时有轮次在跑 — 必然 — 需要确认现有排队语义能承受，先按「主入口优先、子代理排队」验证一次。
- 改名牵动一批既有测试与旧配置 — 很可能 — 用旧名字映射兜住，测试逐个更新到新名字。
- 子代理默认跟父会话同一个目录 — 中等 — 不传 `work_root` 时两只子代理会改同一份文件；工作树有 git 这个前置依赖，缺 git 时只能靠「一次只派一件会改同一批文件的事」兜住，不能因此拦住 Super Agent 模式。
- 去掉人工验收关卡后成果没有人「收下」 — 低 — 验收落在 PR review 与 merge，这是原文的做法，不是遗漏。
- Router 无法查询子代理进度，`sub_agent` 只有 create / close / delete — 低 — 按原文它不需要轮询，等汇报即可；若实际发现需要，再补一个只读动作。

## 未答问题

- 暂无阻塞项。
