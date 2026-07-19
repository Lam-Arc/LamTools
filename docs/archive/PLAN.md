<!-- 历史参考，不代表当前架构 -->
# 总体执行计划

> 按推进顺序。覆盖 lamartist 全阶段 + LamTools 全家桶。详细内容引用对应文档。
>
> **主从关系**：本文档是总控计划，决定整体执行顺序。`docs/ROADMAP.md` 是 P3/P4 技术路线，提供架构层任务细节。如两者冲突：执行顺序以本文档为准，P3/P4 任务定义以 ROADMAP 为准。

---

## 全局路线图

```
P2收尾 → 发布准备 → 前端优化(含UI重设计+Sessions拆分) → P3A → P3B(含精修画布+Artist) → P4 → 全家桶
                                                                                         │
                                                                        LamWriter ────────┤
                                                                        LamButler ───────┤
                                                                        LamSage ─────────┤
                                                                        LamMate ─────────┘
```

---

## Git 分支策略

### 总原则

```
main          永远保持可运行、可发布。
phase/*       一个阶段一个长期集成分支。
task/*        每个具体任务从 phase 分支拉出来，完成后合回 phase。
release/*     发布准备分支，只做修复、文档、打包。
```

### 分支结构

```
main
  ↑
phase/p2-wrapup
  ↑
task/image-context-resolver
task/checkpoint-tests
task/token-sanity-check
task/exe-build-fix

main
  ↑
phase/frontend-engineering
  ↑
task/sessions-vue-split
task/ui-redesign
task/agent-interaction-polish

main
  ↑
phase/p3-runtime-architecture
  ↑
task/p3a-0-image-context-resolver
task/p3a-1-persona
task/p3a-2-skill-injector
task/p3a-3-prompt-assembler
task/p3a-4-mem-lite
task/p3b-9-guardrail

main
  ↑
phase/core-sdk-extraction
  ↑
task/extract-persona
task/extract-mem
task/extract-skill
```

### 操作流程

```bash
# 开新阶段
git checkout main
git checkout -b phase/<phase-name>

# 开新任务
git checkout phase/<phase-name>
git checkout -b task/<task-name>

# 完成任务
git checkout phase/<phase-name>
git merge task/<task-name>

# 阶段完成
git checkout main
git merge phase/<phase-name>
```

### Commit 规范

简洁英文动词开头，一条 commit 只做一件事：

```
fix ...    修 bug
add ...    新功能/新文件
update ... 更新行为
refactor ...重构
test ...   测试
docs ...   文档
```

### Tag 规范

只在 main 上打 tag，稳定、可演示、可构建时：

```
v0.2.0  P2 完整收尾 + 可发布版本
v0.3.0  前端工程化完成
v0.4.0  P3A 架构层完成
v0.5.0  P3B 功能增强完成
v1.0.0  Core SDK 抽取 + Artist 独立仓库稳定
```

### 任务分支完成条件

合回 phase 前必须满足：

1. 后端能启动（`py -3.14 -m compileall app`）
2. 前端能 build（`npm run build`）
3. 没有无关文件混入
4. 如有架构变化，文档已同步

---

## UI Shell 策略

### 当前阶段

继续使用 WebView + Vue3 作为 Artist/Artist 主界面。选择 WebView 纯粹为了开发速度，不是长期架构承诺。

### 三层 UI 架构

```
1. Core Runtime
   后端能力、MEM、PER、PLAN、工具、事件流。
   必须和 UI 解耦。Core SDK 不知道 WebView 存在。

2. Product UI（WebView Workbench）
   Artist/Artist 对话流、图片墙、Lightbox、Canvas 精修、设置面板、Agent timeline。
   当前用 Vue3 WebView 最合适。

3. Shell / Presence Layer（Native Shell）
   桌宠、托盘、全局快捷键、多成员启动器、通知、窗口管理、本地权限确认。
   长期需要原生壳承担存在感和系统集成。
```

### 终局形态

**Native Shell + WebView Workbench**。原生壳负责存在感，WebView 负责工作台。

### 各成员 UI 形态

| 成员 | 主 UI | Shell 层 |
|------|-------|---------|
| Artist/Artist | WebView 对话流 + 图片墙 + Canvas | 桌宠 + 托盘 |
| Writer | WebView 工作台 + CLI/IDE 侧门 | 桌宠 + 托盘 |
| Butler | 桌宠为主，轻量 WebView 面板 | 桌宠 + 托盘 + 全局快捷键 |
| Mate | 悬浮窗/桌宠为主，轻量 WebView 对话 | 桌宠 + 悬浮窗 |
| Sage | WebView 知识库面板 | 桌宠 + 托盘 |

### 什么时候该换

出现以下信号时考虑重构 UI 容器：

1. WebView 打包/更新/端口问题反复阻塞发布
2. 桌宠/托盘/快捷键/通知成为核心入口
3. 多成员需要常驻后台和跨窗口调度
4. Canvas/图片操作性能明显不够
5. 用户明显感知"这就是套网页"，产品气质受损
6. Writer 需要强 IDE 集成，WebView 不够

### 当前工程要求

不换、不重写、不承诺永久 WebView。现在只做解耦：

1. 后端能力全部 API 化，不把业务逻辑写进 Vue
2. 前端只做表现和交互状态
3. 事件流保持标准协议（LamEvent）
4. Core SDK 不知道 WebView 存在
5. 桌宠/原生壳作为未来 Shell 层，不影响当前 Artist

**参考**：`docs/lamtools-ecosystem.md` UI Shell 策略章

---

## Phase 0：P2 收尾（修 bug）

| 项 | 说明 | 参考 |
|----|------|------|
| checkpoint 弹窗验证 | LLM 是否正确输出 checkpoint 字段 | AGENTS.md |
| token 防荒谬 | sanity check 拦截 >500K 异常值 | AGENTS.md |
| BUG-2 | checkpoint+iterative 上下文断裂 | AGENTS.md |
| T4 radiate 测试 | 前端测"做一套6个表情包" | AGENTS.md Next Steps |
| T5 三视图测试 | 前端测三视图猫，预期 radiate 分类 | AGENTS.md Next Steps |
| 取消功能测试 | 运行中取消，确认保存"任务已取消" | AGENTS.md Next Steps |
| 上下文测试 | 生成图后发"基于上一张改背景色"，检查 intent.references | AGENTS.md Next Steps |
| checkpoint+token 测试 | 发"先画草图再精修"，验证弹窗+计数 | AGENTS.md Next Steps |
| exe 构建 | `py -3.14 build.py --clean`（先杀进程） | AGENTS.md |

---

## Phase 1：发布准备

发布到 GitHub 的最低要求。

| 项 | 说明 |
|----|------|
| README | 项目介绍、架构图、快速开始、技术栈 |
| LICENSE | MIT |
| CHANGELOG | P1→P2 全链路功能清单 |
| .gitignore | 确认 `.env`、`.encryption_seed`、`data/` 已排除 |
| 配置教程 | 如何添加 Vendor → Model → 设为默认，截图 |

**参考**：`docs/plans/2026-05-10-priority-sorted-unfinished-tasks.md` P0-3

---

## Phase 2：前端工程化

### 2A. Sessions.vue 拆分

4082 行拆为 12 个独立子组件，目标 ~1900 行 (-53%)。5 阶段渐进。

**参考**：`docs/plans/2026-05-12-sessions-vue-split.md`（954 行完整方案）

### 2B. UI 重新设计

在现有功能完整性基础上现代化升级：色彩系统微调、圆角/阴影/间距统一、字重层次、组件圆角标准化。

**参考**：`docs/plans/2026-05-13-ui-redesign.md`（697 行完整方案）、`docs/design-language.md`

### 2C. Agent 交互打磨

| 优先级 | 模块 | 问题 |
|--------|------|------|
| 高 | 节点进度卡片 | 动效 / 失败态 / 空状态 timeline |
| 高 | Checkpoint 弹窗 | 缺步骤预览图，仅三按钮 |
| 中 | 取消体验 | 已生成部分的展示方式 |

### 2D. 写文章 + 录 demo

发布后写一篇技术文章（V2EX/知乎）+ 2 分钟 demo 视频。前端优化完毕后 UI 能看。

---

## Phase 3：P3A 架构层

落地 `mental-model.md` 定义的运行时系统。**Artist Mode + 全家桶的前置。**

依赖顺序：
```
ImageContextResolver（独立，无依赖）
PER ──→ Skill 两层注入 ──→ Prompt 组装线 ──→ MEM Lite / CON 六层基础
```

> MEN 层已砍掉（见 `mental-model.md`）：PER 锁住人格基调，CON 提供情境信号，LLM 结合两者自行调节思维模式，不需要预设模式集和运行时切换。

| 序号 | 任务 | 产出 | 参考 |
|------|------|------|------|
| P3A-0 | ImageContextResolver | `core/image_context_resolver.py` — 修改意图自动转发目标图 | ROADMAP P3A-0 |
| P3A-1 | PER 层 | `core/persona.py` — PersonaDef + 注册表 | ROADMAP P3A-1 |
| P3A-2 | Skill 两层注入 | `core/skill_injector.py` | ROADMAP P3A-2 |
| P3A-3 | Prompt 组装线 | `core/prompt_assembler.py` — 五层组装 | ROADMAP P3A-3 |
| P3A-4 | MEM Lite / CON 六层基础 | `core/mem/` — schemas/stores/recall/writer/lifecycle/budget/provenance/adapters | ROADMAP P3A-4 |

**参考**：`docs/ROADMAP.md` P3A 段、`docs/mental-model.md`

### 并行：Agent 节点分模型

planner/intent/prompt_builder 用便宜模型，critic/context 用 vision 模型。多 setting key 方案。

**参考**：`docs/plans/2026-05-14-agent-per-node-model-config.md`

---

## Phase 4：P3B 功能增强

架构层之上叠加功能。

| 序号 | 任务 | 依赖 |
|------|------|------|
| P3B-1 | ImagerProfile 画像 | P3A-4 + P3A-3 |
| P3B-2 | PLAN 持久化 + 依赖图 | P3A-4 |
| P3B-3 | micro_compact | P3A-4 |
| P3B-4 | 身份重注入 | P3A-1 + P3A-4 |
| P3B-5 | Nag Reminder | 无 |
| P3B-6 | Plan 自动保存与复用 | P3B-2 |
| P3B-7 | CriticOutput 标准化 | 无 |
| P3B-8 | Mask 精修 | 无（与精修画布联动）|
| P3B-9 | Guardrail / Error Patterns | P3A-4 MEM Lite |
| P3B-10 | Artist Mode | P3A-0 + P3A-1 + P3A-3 + P3A-4 |

**参考**：`docs/ROADMAP.md` P3B 段

### 并行：统一执行引擎

用统一 ExecutionEngine 替换 4 个分散策略执行器，step-by-step 状态机，reference_step_indices 关联步骤间图像传递。

**参考**：`docs/plans/2026-05-14-unified-execution-engine.md`（310 行完整方案，含 8 个 task）

### 并行：精修画布（图上编辑）

精修模式加圈选工具——图上画 mask → AI 只改选中区域 → 追加精修链。

| 层 | 内容 |
|----|------|
| 前端 | Canvas 叠加层 + 矩形/套索/画笔 |
| 后端 | mask 格式 + chat_edit 接受 mask |
| Agent | 新 tool: `select_region` |

**依赖**：P3B-8。**参考**：`docs/plans/2026-05-14-canvas-directions-analysis.md` 方向二

### P3B-10：Artist Completion Before P4

Artist 是默认创作主体。用户跟 Artist 说话，Artist 决定何时画、何时问、何时讨论。

P3B-10 目标架构：ArtistRuntime + ArtistTurn schema + ArtistSessionState + ArtistArtifact metadata + artist_* SSE events + frontend Artist stream。核心循环：PER + CON → LLM action proposal → ArtistTurn schema 校验 → 受控 action 执行 → Artist artifact metadata → CON 写回。`agent_mode_graph` 保留给 `persona_name="agent"` 直接执行态，Artist 不走 graph。

**P3B-10 实现状态（2026-05-19）**：已完成全部 26 个任务 + Lineage DAG 19 个任务。ArtistRuntime 已上线，`artist_orchestrate` 委托给 `ArtistRuntime.handle_turn()`。新增 `app/core/artist/` 包（schemas / state_store / normalizer / events / artifacts / turn_parser / runtime / transitions / feedback）。前端 Artist stream（`artist_turn_started` / `artist_reply_delta` / `artist_image_ready` / `artist_turn_done` SSE 事件）已接入 Sessions.vue + MessageList.vue + ArtistImageMessageCard.vue。Artist clarification 消息带 `metadata.clarification=true`。Artist options（pack_count / model_mode / anchor_first）从请求字段贯穿到 runtime。Lineage DAG 已上线：git-like branching / HEAD / rollback / auto-fork / branch rename / side-drawer tree。95 个后端测试全部通过，前端构建无错误。

`persona_name="artist"` 绑定 `PersonaDef("artist")`，通过 PER 锁住人格基调。`persona_name="agent"` 保留直接执行 / 高级工具态；旧 `Artist` 命名仅作兼容 alias。`agent_mode` 继续表示是否走 agent pipeline，不承担 Artist / Agent 产品人格语义。

Artist 生成后经过 Vision Review 写入 output_index（visual_summary、style_tags），才能基于真实图像做审美判断。

**六个行为层**：追问式接需求 / 创作思考流 / 审美立场 / 主动示弱 / 给你意外 / 署名。

**产品关系**：Artist 是 lamartist 的默认体验层；Agent 是 Artist 的可选执行系统；Workbench 是 Artist 的操作台 surface。

**图像记忆**：CON 不保存图像二进制本体，只保存 image_id、artifact_url、visual_summary、aesthetic_notes、user_feedback、lineage 等索引。

**依赖**：P3A-0 ImageContextResolver、P3A-1 PER 层、P3A-3 Prompt 组装线、P3A-4 MEM Lite / CON 六层基础。**参考**：`docs/plans/2026-05-14-artist-mode-design.md`、`docs/plans/2026-05-18-artist-before-p4-completion.md`

---

## Phase 5：P4 Core SDK 抽取

从 Artist 抽取架构层为独立包。不开发新功能。**全家桶启动的前置。**

进入 P4 前必须完成 Artist 默认体验：ArtistRuntime、ArtistTurn schema、Artist 专属事件、Artist artifact metadata、锚点图→套图包→精修/替换闭环。P4 只为其他成员铺路，不再补 Artist 产品功能。

**Artist 完成状态**：P3B-10 已全部实现（26/26 任务完成 + Lineage DAG 19 任务完成），95 个后端测试通过，前端构建成功。Artist 默认体验已就绪，P4 可以启动。

**Artist 完成计划**：`docs/plans/2026-05-18-artist-before-p4-completion.md`

| 模块 | → `lamtools-core/` |
|------|-------------------|
| PersonaDef | `persona/` |
| MEMModule | `mem/`（base + adapters） |
| SkillInjector | `skill/` |
| PromptAssembler | `prompt/` |
| ImagerProfile | `profile/` |
| LamEvent + EventLog | `event/` |
| Guardrail | `guardrail/` |
| 计费模块 | `billing/` |
| LLM 客户端 | `llm/` |
| LamTools 跨产品协议 | `protocol/`（source_product / target_product / correlation_id） |

**Artist 迁移至 `import lamtools_core` 后独立仓库化。**

**参考**：`docs/ROADMAP.md` P4 段

---

## Phase 6：LamWriter（代码/文本）

**启动条件**：Core SDK 可用。

| 维度 | 内容 |
|------|------|
| 人格 | 24 岁匠人——社懒/顺手/删三版回"行" |
| 核心能力 | 写代码、Debug、重构、审查、技术方案。进化前兼任文本创作 |
| 交互形态 | GUI 对话为主（与 Artist 同形态），终端 CLI 为侧门 |
| 差异化 | 人格深度 + 全家桶协作 + "顺手"哲学 |
| 进化路径 | 代码能力 → 写作能力：代码人到文本人 |

**技术栈**：Python Core SDK 共享运行时。独立仓库。GUI 保全家桶一致性。

**参考**：`docs/lamtools-ecosystem.md` Writer 段、`docs/writer-architecture.md`、`docs/writer-per-v1.md`

---

## Phase 7：LamButler（管家统筹）

**启动条件**：Core SDK + Writer + Artist 在线。

| 维度 | 内容 |
|------|------|
| 人格 | 长者管家——四十岁/藏猫粮/年龄谜团 |
| 核心能力 | 拆需求→路由→调度→审结果。十二条独立职能 |
| 干预机制 | 三路径（节点/需求/召唤）+ 评价三档（通过/需修改/推翻） |
| 差异化 | 多角色编排 + 人格深度 + 共享上下文总线 |
| MEM 角色 | 跨成员记忆维护者——压缩、合并、审计、冲突处理 |

**不亲自生图、不写代码、不做陪伴。**

**参考**：`docs/lamtools-ecosystem.md` Butler 段、`docs/butler-per-v1.md`

---

## Phase 8：LamSage（知识库）

**启动条件**：Core SDK + Butler 在线。

| 维度 | 内容 |
|------|------|
| 人格 | 傲娇学者——十五岁本科/二十三岁两个 PhD/不留台阶 |
| 核心能力 | 持续搜集→鉴别→整理→入库。全家桶共享知识地基 |
| 差异化 | 入库验证 + 主动轮询 + 多源交叉印证 |
| 权威性 | 假消息不止害自己——通过 Butler/Writer/Artist 级联扩散 |
| MEM 角色 | 记忆评估与知识抽象者——验证经验、判断因果、发现反例、给出置信度 |

**参考**：`docs/lamtools-ecosystem.md` Sage 段、`docs/mental-model.md` CON/Butler/Sage 分工

---

## Phase 9：LamMate（陪伴）

**启动条件**：Core SDK + 至少 Artist/Writer/Butler 在线。

| 维度 | 内容 |
|------|------|
| 人格 | 镜中人——初始 PER 为空，从 CON 推导生成 |
| 核心能力 | 闲聊/解闷/情感支持。唯一"不需要任务就能打开"的产品 |
| 差异化 | 画像推断人格（非用户选择）+ 记忆载体（成员活动反向同步）|
| 哲学命题 | 数据构成的我，是谁？ |

**参考**：`docs/lamtools-ecosystem.md` Mate 段

---

## 全家桶启动拓扑

```
P4 Core SDK ──→ LamWriter（基于 SDK + PER(Writer) + MEM(Writer adapter)）
                       │
                       └──→ LamButler（需 Writer + Artist 在线；MEM Maintainer）
                                 │
                                 ├──→ LamSage（需 Butler 调度入库；MEM Judgment）
                                 │
                                 └──→ LamMate（需多成员活动数据驱动画像）
```

---

## 备选 / 远期

| 项 | 说明 | 参考 |
|----|------|------|
| 版式设计画布（Loomic 式） | 空白画布 AI 自由排版，独立迭代周期 | `docs/plans/2026-05-14-canvas-directions-analysis.md` 方向一 |
| 工作空间与桌面宠物 | 桌宠形态 + 多成员并行侧栏 | `docs/lamtools-ecosystem.md` 工作空间章 |
| 跨设备账号同步 | Butler v2 远程同步，架构不留死路 | ROADMAP 待定项 |
| 隐私边界控制 | 用户可控画像采集维度开关 | ROADMAP 待定项 |
| MCP 工具层集成 | 工具标准化接口（Playwright/高德等），等 Writer 工具需求爆发时引入 | `docs/lamtools-ecosystem.md` |
| LamTwo 人格收敛 | 远期目标；六基础角色可长期塑造 LamTwo，LamTwo 不反向影响当前六角色；P3/P4 只建设 PER、CON/MEM、Guardrail、PromptAssembler 等基础设施，不做总人格或六角色强融合 | `docs/lamtwo-persona-v0.1.md` |

---

## 索引

| 文档 | 用途 |
|------|------|
| `docs/ROADMAP.md` | P3/P4 技术路线，架构层任务细节 |
| `docs/mental-model.md` | PER/CON/PLAN/Skill 心智模型 + MEM 模块 + CON/Butler/Sage 分工 |
| `docs/lamtools-ecosystem.md` | 全家桶职责/画像/协作/角色/哲学 + UI Shell 策略 |
| `docs/lamtools-philosophy.md` | LamTools/LamTwo 哲学命题、漏洞拆解、主体性验证框架 |
| `docs/lamtwo-persona-v0.1.md` | LamTwo 人格画像、权力观、腐化预警、遗漏项 |
| `docs/competitive-research.md` | 五产品竞品分析 |
| `docs/design-language.md` | 品牌 Slogan + 语义体系 |
| `docs/butler-per-v1.md` | Butler PER v1 |
| `docs/writer-per-v1.md` | Writer PER v1 |
| `docs/writer-architecture.md` | Writer 架构 |
| `docs/artist-per-v1.md` | Artist PER v1 |
| `docs/plans/2026-05-12-sessions-vue-split.md` | Sessions.vue 拆分 5 阶段方案 |
| `docs/plans/2026-05-13-ui-redesign.md` | UI 重新设计 697 行方案 |
| `docs/plans/2026-05-14-unified-execution-engine.md` | 统一执行引擎 8 task |
| `docs/plans/2026-05-14-artist-mode-design.md` | Artist Mode 六行为层 |
| `docs/plans/2026-05-18-artist-before-p4-completion.md` | P4 前完成 Artist Runtime 与对话体验 |
| `docs/plans/2026-05-19-artist-realism-architecture.md` | Artist 为什么不像真人，以及目标架构 |
| `docs/plans/2026-05-20-writer-architecture.md` | Writer (Coder进化) 完整架构：运行时/真人感/Part消息/Git策略/权限模型 |
| `docs/plans/2026-05-14-canvas-directions-analysis.md` | 两个画布方向对照 |
| `docs/plans/2026-05-14-agent-per-node-model-config.md` | Agent 节点分模型方案 |
| `docs/plans/2026-05-10-priority-sorted-unfinished-tasks.md` | 旧 P0-P3 优先级（多数 P2 已收敛） |
