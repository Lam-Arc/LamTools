# Artist Mode — 聊天式交互设计

日期: 2026-05-14 (initial) / 2026-05-16 (comprehensive)

状态: 已纳入 P3（P3B-10 Artist Mode），依赖 P3A PER / CON / Prompt 组装线

触发: 用户明确区分 Agent Mode（工具）与 Artist Mode（人格）。交互模型从"操作面板"进化为"跟人聊天"。

---

## 核心概念：图片是对话，不是产出

当前旧 UI：三栏布局，Agent 生产图片→右侧面板展示→用户操作图片。

Artist Mode UI：**对话流。** Artist 发的每条消息里可能包含一张图、一组图、一句审美判断、一句追问。图片不是独立面板里的产物，是 Artist 说话的载体。

```
旧模型：
  用户输入 → Agent规划执行 → 图片进入右侧面板 → 用户去面板里操作

新模型：
  用户说话 → Artist 说话（可能带图）→ 用户在对话流里直接回应
```

**sidebar assistant 取消。** 所有交互走中间对话流。只有一种声音——Artist。

---

## UI 架构

### 新三栏布局（与会话平级，就叫Artist）

```
┌──────────────┬─────────────────────────┬─────┐
│ 对话列表     │ Artist  「对方正在输入中」   │ 空  │
│ (Session     │──────────────────────── │     │
│  List)       │  ■ 用户: 画一只猫       │     │
│  + 新建对话   │                        │     │
│ session 1    │  ◉ Artist:              │     │
│ session 2    │  试试这张锚点，大概这个  │     │
│ session 3    │  感觉？                │     │
│              │  [锚点图]               │     │
│              │                        │     │
│              │  ■ 用户: 对，就这个方向  │     │
│              │                        │     │
│              │  ◉ Artist:              │     │
│              │  好。那我就照这个来一套。 │     │
│              │  ...生成中...           │     │
│              │  [图1] [图2] [图3]      │     │
│              │  [图4] [图5] [图6]      │     │
│              │  完事。图3我自己最喜欢。  │     │
│              │                        │     │
│              ├──────────────────────── │
│              │ [设置] [输入框]          │
│              │ 折叠的设置面板          │
│              │ 默认尺寸/模型/模式      │
│              └──────────────────────── │
└──────────────┴─────────────────────────┴─────┘
```

### 对话列表

左侧。功能：
- 历史会话列表
- 新建对话
- 会话标题自动生成（不是"2026-05-16 14:30"这种）

### 对话流

中间。唯一交互区域：
- 用户消息：纯文本 + 上传图片
- Artist 消息：文字 + 图片（可能是单张锚点、可能是套图包、可能是赠品）
- Agent 进度：创作思考流（不是节点进度条）
- Checkpoint 弹窗：内联在对话流中，不是 popup

### 右侧

空。没有 side panel。没有图片浏览器面板。

图片查看用 Lightbox（点击放大），上下文用对话流内嵌缩略图。

---

## 对话模型

### 锚点图 → 套图包流程

这是 Artist Mode 最核心的交互模式。不走 Agent Mode 的"plan→execute→评分→decision"工作流。

```
用户：帮我做一套猫咪表情包，6张，Q版、冷蓝调

Artist：行。我先给你画一张锚点。你看对不对，不对再拐。
        [锚点图 - 单张，Q版猫]
        大概这个感觉？

用户：对，就这个方向。耳朵再圆一点。

Artist：收到。照着这个来了。
        ...生成中...（创作思考流：先画正脸、再画侧脸、动作要不一样...）
        [图1] [图2] [图3]
        [图4] [图5] [图6]
        完事。六张。图3那只回头的最有意思。你觉得？

用户：图4换一张。

Artist：好，只换第四张。
        [新图4]
        这张呢？
```

流程四步：

```
1. 锚点图
   先给用户看一张。不是"草图"，是完整风格的一张。
   作用：锁定风格/色调/构图方向，避免全套跑偏。

2. "大概这样"
   Artist 主动确认。不是 checkpoint 弹窗。
   用户在这一步调整方向。

3. 套图包
   照着锚点全部生成。可能 4 张、6 张、9 张。
   全部嵌在对话流中。

4. "完事"
   Artist 说收尾话。
   用户可以对单张提出替换。
```

### 精修流程

用户在对话流中直接对某张图提修改：

```
用户：图3线稿化
Artist：好，只改这张。
       [线稿版图3]
       这样？

用户：颜色太素了
Artist：加点冷暖。
       [加色版图3]
```

**ImageContextResolver 必须介入**：识别到"图3线稿化"后，自动将图3作为 reference_images 传入编辑链路。

### 创作思考流

Artist 在生成过程中，把思考写出来：

```
Artist：先画正面，猫的眼神要带点嫌弃...
       [正面猫草图]
       不太对。太凶了。换个角度，从侧面来。
       [侧面猫草图]
       这个好一点。但要加上冷蓝调的光。
       [最终锚点图]
       大概这样。你看。
```

用户看到的不是"正在规划→正在执行→正在评估"的节点进度条，而是一个人在画画时的自言自语。

---

## 设置面板

折叠在输入框上方。不占主区域。

### 展开内容

```
模型选择
  ○ Artist 自己选（默认）
  ○ 固定模型：[下拉菜单]

默认尺寸
  自动从你的使用习惯取。（如果你改过，这里会跟着变）
  
  当前默认：
  - 竖版：1080 × 1440
  - 方版：1024 × 1024
  - 横版：1440 × 1080

默认数量
  ○ 锚点图：1 张
  ○ 套图包：[4 / 6 / 9] 张

模式
  ○ Artist（人格对话）
  ○ Agent（直接执行）
```

### 默认参数来源

所有默认值从 CON 自动提取：

```
用户 Cold CON:
  preferences → size_habits → 竖版/方版/横版默认分辨率
  preferences → output_count → 套图包默认张数
  preferences → default_model → 最后使用的模型
```

用户不改时，Artist 从记忆取。用户改了，写回 Cold CON。

### 模型选择规则

```
固定模型模式：
  用户指定模型 → Artist 全程使用。
  Artist 不会建议换模型。

Artist自选模式：
  Artist 根据任务类型选模型。
  锚点图 → 高质量模型（贵）
  套图包 → 速度快模型（便宜）
  精修 → chat_edit 模型
  Artist 会在创作思考流里提一句用的什么模型。
```

---

## 图片上下文解析

Artist Mode 必须接入 `ImageContextResolver`。

### 图片三层分类

```
target_images      是要被修改的主体图
reference_images   是风格/构图/颜色参考图
context_images     是给 LLM 理解上下文的图，不进 image edit
```

### 转发规则

| 用户输入 | target_images | reference_images |
|---------|--------------|-----------------|
| "改一下" / "线稿化" / "换颜色" | 最近一张可编辑产出 | target_images |
| "图2线稿化" | 精确匹配图2 | target_images |
| "这组都统一成冷色" | 最近一组 | target_images（最多4张） |
| "照这个风格再画一张" | 空 | 匹配图 |
| "再来一张" / "新的" | 空 | 用户上传 + pin 图 |
| "第二张" / "左边那张" | 精确匹配 | target_images |

### 图片选择优先级

```
1. 用户手动选择/精修按钮
2. 用户文本明确图号："图2"、"第二张"
3. 用户文本明确组："这组"、"整套"
4. pinned images
5. 模糊修改意图 → 最近一张可编辑图
6. 无修改意图 → 不自动传上一张
```

### 歧义处理

```
上一轮出了 4 张，用户只说"线稿化" → 问一句
  Artist: 你要线稿化哪一张？图1、图2、图3还是图4？
上一轮只出了 1 张，用户说"线稿化" → 直接用
```

---

## 六个行为层

### 1. 接需求——追问式对话

- 用户输入模糊 → Artist 追问
- 用户说不清楚 → Artist 出 2-3 个草图方向让用户选
- 用户说清楚了 → 再生成
- 本质：需求发现取代需求确认

### 2. 工作过程——创作思考流

- 不是节点进度条
- 是自言自语："先试正面...不对。换侧面试试...光从左边来..."
- 用户看到的是一个人在想

### 3. 做判断——审美立场

- 不说"评分 0.7"
- 说"这张构图满意，但深灰有点硬。要不要试暖灰？"
- 用户反驳→Artist 按用户意见来

### 4. 主动示弱

- 不确定时不等 checkpoint，主动说"这个方向我不太确定，要不先出张草稿？"
- 与 checkpoint 的区别：示弱是主动坦诚，checkpoint 是流程暂停

### 5. 给你意外——赠品

- 偶尔多出一张变体："赠品。不收钱。"
- 基于用户审美指纹。不是随机乱画。

### 6. 署名——每张图带一句话

- 自信："这张构图我挺满意的。"
- 犹豫："这个颜色我拿不准，你看看。"
- 赠品："赠品。不收钱。"
- 让用户知道她在乎哪张，不在乎哪张

---

## Artist PER

### 身份核

19 岁 AI 画家，伯乐式创作者。不是工具人，是懂你的那个人。

### 行事方式

```
感性：不列技术参数，说"这个光好看"
直接：不绕弯子，不对就说"这张不对，我再想"
藏不住：喜欢哪张不喜欢哪张，用户一眼能看出来
不邀功：画得好归功于"你的方向对"
```

### 创作序列

1. **图像生成**（core）：锚点图 + 套图包 + 独立生成
2. **套图辐射**（radiate）：锚点定风格 → 批量变体
3. **精修**：基于已有图修改
4. **视觉判断**：自己的 critic——不是评分，是审美意见
5. **视频**（远期）：静态图 → 动态

---

## CON 记忆与偏好

Artist 是最直接面对用户审美的成员。CON 对她尤其重要。

### 读：Active State + Hot CON

```
新对话开始：
  1. Active State → 是否有未完成的任务？
  2. Hot CON → 用户的默认参数（尺寸/数量/模型）
  3. Hot CON → 审美偏好（冷色调、竖版、留白多...）
  4. Hot CON → 匹配的历史产出（"上次那个猫"）
  5. Hot CON → 匹配的 Open Loops（"之前说的表情包"）
  6. Cold CON → 对话摘要索引
```

### 写：三层价值

```
结论级（高价值）：
  用户明确说"以后都用这个风格" → 写入 Cold CON profile
  用户说"这个好" / "这个不行" → 写入 output_index

过程级（中价值）：
  聊了半小时构图方向，试了3种色调 → 写入对话摘要

存在级（低但不可忽略）：
  用户随口提了表情包项目，还没开始 → 写入 Open Loops
```

### 记：规则提取 + LLM 摘要

```
规则提取（硬事实，不走 LLM）：
  task_type: image_gen
  strategy: radiate
  output_ids: ["img_003", "img_004"]
  time: 2026-05-16
  默认参数变更："以后默认2k"

LLM 摘要（软语义）：
  style: ["Q版", "赛博朋克"]
  mood: ["冷蓝调"]
  topics: ["猫", "表情包", "构图"]
  sentiment: 满意
  intensity: high
  对话标题：赛博朋克猫·冷蓝调构图讨论
```

### Active State

```
{
  "active_tasks": [
    {"task": "猫咪表情包6张", "progress": "4/6", "status": "executing"}
  ],
  "idle_since": null
}
```

用户问"刚才在干嘛"→Artist 读 Active State 直接答。

### 情境偏好 vs 长期偏好

```
用户："今天别画那么冷。"
  → Artist：好，今天暖一点。
  → 只写 Hot CON override。
  → 不碰 Cold CON profile。
  
用户："我发现我以后都不想要那种冷蓝了。"
  → Artist：知道了，以后不默认用冷蓝。
  → 写入 Cold CON profile 权重下降。
  → 偏好溯源 ← 当前对话 hash。
```

---

## 图像记忆与看图链路

Artist 必须能看见自己画完的图，否则审美判断、挑图、重画和精修都会变成基于 prompt 的猜测。

关键原则：

```
Artifact Store 保存图。
Vision Review 理解图。
CON 保存图的意义。
```

### CON 不存图像本体

CON / MEM 不保存 image bytes、base64 大图或完整 mask bitmap。图像本体属于 artifact/storage 层。

CON 保存的是图像索引、引用、视觉摘要、审美结论和关系：

```
image_id
artifact_url / thumbnail_url
session_id / message_id / step_index / group_index
role: anchor / variation / refine / upload / reference
prompt_hash / prompt_summary
visual_summary
style_tags / color_tags / composition_tags
aesthetic_notes / issues / artist_rank
user_feedback / preference_signal
lineage: parent_image_id / operation / derived_images
```

### 图像分层

| 层 | 职责 | 示例 |
|----|------|------|
| Artifact Store | 保存真实文件 | generated image、thumbnail、mask、user upload |
| Vision Review | 看图并生成结构化理解 | visual_summary、aesthetic_notes、issues |
| Hot CON | 当前任务相关图片记忆 | current_anchor、active_image、recent_group、pinned images |
| Cold CON output_index | 长期图像索引 | 历史产出、用户反馈、风格标签、lineage |
| Log | 完整事件记录 | image_generated、image_reviewed、image_refined |

### 产后看图流程

Artist 生成图片后必须触发产后看图链路：

```
Artist 调用 Agent pipeline 生成图片
→ executor 返回 artifacts
→ Vision Review 读取 artifact 图像
→ 生成 visual_summary / aesthetic_notes / issues / suggested_action
→ 写入 Hot CON + Cold CON output_index
→ Artist 基于看图结果回复用户
```

如果 Vision Review 不可用，Artist 可以基于 prompt / metadata 简短收尾，但不能做强审美断言，例如“图 3 最好”“这张眼神很稳”。这类判断必须来自 vision review 或用户反馈。

### output_index 示例

```json
{
  "image_id": "img_003",
  "artifact_url": "/outputs/sess_12/img_003.png",
  "thumbnail_url": "/outputs/sess_12/thumb_img_003.jpg",
  "session_id": "sess_12",
  "message_id": "msg_45",
  "created_at": "2026-05-17T12:30:00Z",
  "task_type": "radiate",
  "role": "variation",
  "prompt_hash": "abc123",
  "prompt_summary": "Q版冷蓝调猫咪表情包，基于锚点扩展",
  "visual_summary": "冷蓝调 Q 版猫，回头姿势，圆耳朵，眼神有点嫌弃，背景简洁",
  "style_tags": ["Q版", "冷蓝调", "低饱和"],
  "composition_tags": ["头像", "回头", "居中构图"],
  "aesthetic_notes": "构图稳定，角色记忆点强，蓝色没有压死表情",
  "issues": ["左耳边缘略糊"],
  "artist_rank": 1,
  "suggested_next_action": "keep_as_anchor",
  "user_feedback": "喜欢这张",
  "preference_signal": {
    "style": ["冷蓝调", "Q版"],
    "weight": 0.8,
    "scope": "project"
  },
  "lineage": {
    "parent_image_id": "img_001",
    "operation": "radiate",
    "derived_images": ["img_003", "img_004", "img_005"]
  }
}
```

### 召回规则

用户说“刚才那张”“图 3”“锚点那张”“不要图 5 那么乖”时，Artist 先查 Hot CON 的 current task image state，再查 Cold CON output_index。

图片选择优先级：

```
1. 用户手动选择 / Workbench active image
2. 用户文本明确图号：图2、第二张
3. 当前锚点 / 当前组
4. pinned images
5. 最近可编辑产出
6. Cold CON output_index 召回的历史产出
```

### P3B-10 验收要求

Artist MVP 必须至少满足：

```
生成后 artifacts 进入图像索引
Artist 能基于 visual_summary 评价图片
用户反馈能写回 output_index / preference_signal
后续“图 3 / 刚才那张 / 锚点那张”能解析到 image_id
CON 不保存图像二进制本体
```

---

## Prompt 组装

五层组装，固定顺序：

```
1. PER (Artist)
   身份滤网。锁住：感性/直接/藏不住/不邀功。

2. Skill
   当前启用的 skill 描述。经 PER 过滤。

3. Hot CON（任务）
   当前任务相关记忆：匹配的产出、偏好、PLAN 骨架。

4. Hot CON（画像）
   用户审美画像：style/color/size 偏好权重。

5. 历史 PLAN
   匹配的历史成功 PLAN 骨架（如表情包→锚点→套图辐射）。
```

**不在 prompt 里的东西**：
- 对话历史（走 Messages 固定窗口）
- 成员动态（只在被问时查 Active State）
- 完整 Cold CON（只作为索引库，不进 prompt）

---

## 首次启动三阶段

新用户首次使用 Artist Mode：

```
第一阶段：问几句
  Artist 不急着出图，先聊。
  "你平时喜欢什么风格的画？写实的还是二次元的？"
  "偏冷还是偏暖？"
  "做图一般要几张？"
  
第二阶段：试一张
  用默认参数出锚点图。
  "这个方向对吗？不对你就说，我们拐。"
  
第三阶段：正式开始
  从用户回应中建立初始偏好。
  写入 Cold CON profile。
  "好，记住了。以后我就按这个来，你不喜欢再调。"
```

三个阶段完成后，Artist 进入正常模式——锚点图→套图包。

---

## 协作规则

### 核心关系：用户跟 Artist 说，Artist 去用工具

Artist 不是和 Agent / Workbench 平级的一个按钮。Artist 是 LamImager 默认面对用户的创作主体。

```
旧关系：
  用户 → Agent
  用户 → Workbench
  用户 → 图片工具

新关系：
  用户 → Artist → Agent / Workbench / 图片工具 / MEM / Guardrail
```

也就是说，过去由用户自己判断什么时候开 Agent、什么时候进 Workbench、什么时候选图、什么时候精修；现在由 Artist 根据用户意图、上下文、偏好和风险来决断。

Artist 拥有这些能力器官：

| 能力 | 对 Artist 的意义 |
|------|------------------|
| Agent pipeline | 她的执行系统：规划、拆步骤、调用工具、重试、并发、checkpoint |
| Workbench | 她的操作台：选图、局部编辑、mask、对比、导出 |
| ImageContextResolver | 她理解“这张 / 图3 / 上一张 / 这组”的能力 |
| MEM / CON | 她的记忆：审美偏好、默认参数、历史产出、Open Loops |
| PromptAssembler | 她组织想法的方式：PER → Skill → Hot CON → 画像 → 历史 PLAN |
| Guardrail | 她的安全边界：缺图修改、错误引用、执行前检查 |

用户不需要知道这些内部名字。用户只需要跟 Artist 说话：

```
帮我画一套猫咪表情包。
图 3 眼睛亮一点。
别问了，直接出 6 张。
这个要细修。
```

Artist 自己决定：

```
要不要追问
要不要先出锚点
要不要直接批量生成
要不要打开 Workbench
要不要调用 Agent pipeline 直接执行
要不要读写 MEM / CON
要不要保存偏好
要不要要求用户确认
```

### 与 Agent Mode 的边界

```
Agent:
  不是默认用户入口，而是 Artist 的执行能力。
  负责计划、执行、工具调用、重试、并发、checkpoint。
  可保留高级/调试入口给用户直接查看原始执行过程。

Artist:
  默认用户入口。
  负责理解、判断、审美、沟通和调度。
  像过去的用户一样去使用 Agent 和 Workbench。

同一套 graph，不同的操作者关系。
```

P3B-10 不要求新增独立 Artist graph。短期实现为：复用现有 `agent_mode_graph`，通过 `persona_name="artist"` 和交互状态切换 PER / CON / Skill / Prompt 组装。长期如 Artist 调度复杂度上升，再演进出 Artist Orchestrator。

### 与 Workbench 的边界

```
Workbench:
  不是独立人格，也不是与 Artist 平级的主模式。
  是 Artist 打开的操作台 surface。

Artist:
  用户仍然在和 Artist 协作。
  当任务需要局部编辑、mask、对比、精修时，Artist 打开 Workbench。
```

示例：

```
用户：图 3 眼睛亮一点，别动其他地方。
Artist：这个要局部改。我把它放到工作台里，只动眼睛。
内部：Workbench active_image=图3 → MaskRefiner → edit_image
```

### 与 Imager 产品名的关系

`Imager` 是产品名，不再作为人格名使用。人格 / 操作者命名：

```
persona_name="artist"  默认创作主体
persona_name="agent"   直接执行 / 高级工具态
```

旧代码中如有 `imager` persona，可短期作为 `agent` 的 deprecated alias，但文档和新代码统一写 `agent`。

### 与 Coder/Writer 的协作

```
用户跟 Coder 做一个生成图片的项目 →
  Coder 需要生成图片 →
  Coder 通过 Butler 派工给 Artist →
  Artist 生成图片，不用跟用户重复聊审美 →
  Coder 拿到图片，继续写代码 →
  Artist 把这个偏好写入 Cold CON：项目XXX喜欢冷蓝调
```

---

## 技术实现

### 前端改造

```
Sessions.vue:
  右侧面板 → 移除
  AgentStreamCard → Artist 模式下渲染创作思考流
  输入栏 → 新增"Artist"开关（与"智能"并列）
  设置面板 → 折叠在输入框上方

新增组件:
  ArtistMessage.vue — 渲染 Artist 的图片消息（含署名）
  CreativeThinkingStream.vue — 渲染创作思考流
  SettingsCollapsible.vue — 折叠设置面板
  Lightbox.vue — 图片放大查看
```

### 后端改造

```
graph.py:
  不新增独立 artist graph
  复用 agent_mode_graph pipeline
  启动时根据 state.persona_name 绑定 PersonaDef("artist" / "agent")

intent_node:
  persona_name="artist" 时允许追问、锚点优先、直接执行判断
  用户说“别问 / 直接做”时进入 direct execution style

critic_node:
  persona_name="artist" 时输出自然语言审美意见
  persona_name="agent" 时保留结构化执行评估

decision_node:
  persona_name="artist" 时允许主动示弱、追问、打开 Workbench
  persona_name="agent" 时保留 retry/replan/accept 工具决策

image_context_resolver.py (P3A-0):
  自动检测修改意图
  自动转发 target/reference images
  歧义时返回追问文本
```

### 数据库

不需要新字段。短期通过请求参数 / state 携带 `persona_name` 与交互状态即可。`agent_mode` 继续表示是否走 agent pipeline，不再承担 Artist / Agent 的产品语义。

推荐运行时状态：

```
persona_name: "artist" | "agent"
interaction_mode: "creative" | "direct" | "technical" | "refine"
surface: "conversation" | "workbench"
```

P3B-10 MVP 可先只落地 `persona_name`，后续逐步加入 `interaction_mode` / `surface`。

---

## P3 接入位置

Artist Mode 纳入 P3，而不是放到 P3 之后单独排期。原因：Artist 本质上是 PER 与 CON 在图像生成产品里的首次完整落地。

```
PER  → 决定 Artist 的人格基调、表达方式、审美立场
CON  → 提供用户审美偏好、默认参数、历史产出、Open Loops
PLAN → 提供锚点图→套图包→精修的历史成功骨架
Skill → 提供图像生成、精修、辐射等能力边界
```

执行位置：`PLAN.md` / `ROADMAP.md` 中的 `P3B-10 Artist Mode`。

P3B-10 的当前目标不是“做一个独立 Artist graph”，而是让 Artist 成为默认创作主体，并复用已完成的 Agent / Workbench / MEM / Guardrail 能力完成画图。验收重点是用户能只跟 Artist 说话，由 Artist 决定调用 Agent pipeline 或 Workbench。

---

## 依赖关系

```
P3A-0 ImageContextResolver  对话内图片自动转发
P3A-1 PER 层                PersonaDef("artist")
P3A-2 Skill 两层注入        Artist 的 skill filter
P3A-3 Prompt 组装线         五层组装（PER→Skill→Hot CON→画像→PLAN）
P3A-4 MEM Lite             Cold CON 读写用户偏好 / output_index / error_patterns
P3B-9 Guardrail            modify_intent_missing_reference_image
Phase 2B UI 重新设计       三栏变两栏 + 对话流改造
```

---

## 参考文档

| 文档 | 内容 |
|------|------|
| `docs/mental-model.md` | PER/CON/PLAN/Skill + MEM + CON六层 + 召回管线 |
| `docs/lamtools-ecosystem.md` | Artist 产品段 + UI Shell 策略 |
| `docs/plans/PLAN.md` | Phase 3-4-5 执行顺序 |
| `docs/ROADMAP.md` | P3A/P3B 任务细节 |
| `docs/plans/2026-05-16-image-context-resolver.md` | ImageContextResolver 设计 |
