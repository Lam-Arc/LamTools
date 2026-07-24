# 竞品开源研究档案

> 存于 2026-05-15。全场竞品分析和开源参考源码清单。

---

## 1. 五产品竞品格局

### LamButler — 最接近对手：OpenClaw / 远敌：Notion AI Agent

#### OpenClaw

- **仓库**: https://github.com/openclaw/openclaw（372K stars, MIT）
- **定位**: Your own personal AI assistant. Local-first gateway, multi-channel inbox.
- **核心能力**:
  - 全渠道接入：WhatsApp/Telegram/Slack/Discord/Signal/iMessage/WeChat/QQ 等 20+ 渠道
  - 本地优先 Gateway 控制面：session、channels、tools、events
  - 多 Agent 路由：按渠道/账号/对等方分流到独立 workspace agent
  - 语音唤醒 + Talk Mode（macOS/iOS/Android）
  - Live Canvas：agent 驱动可视化工作空间，支持 A2UI
  - 技能系统：bundled/managed/workspace skills，社区 ClawHub
  - 沙箱安全：Docker 沙箱 + SSH/OpenShell 后端，白名单工具
  - 桌面应用：macOS menu bar app，桌面宠物 Molty 龙虾
  - 技术栈：Node 24 + TypeScript + pnpm workspace

**与 Butler 关键差异**：

| 维度 | OpenClaw | LamButler |
|------|----------|-----------|
| 架构 | 单 Agent + 多入口 | 多 Agent 编排中心 |
| 核心理念 | 一个助手走天下 | 一个管家调度一个团队 |
| 角色深度 | Molty 龙虾吉祥物（浅层人格） | 管家完整人设：长者/藏猫粮/年龄谜团/哲学命题 |
| 干预机制 | 用户手动控制 | 三路径干预（节点/需求/召唤）+ 评价三档 |
| 上下文模型 | session-based | PER/CON/PLAN/Skill 四系统 + 共享上下文总线 |
| 画像体系 | 基础偏好记忆 | 五成员交叉印证 + 权重机制 |
| 知识管理 | 技能文件系统（SKILL.md） | Sage 成员作共享知识地基，非技能文件层 |

**深度对照**：

OpenClaw 解决问题像「一个律师」——给他配工具、skills、渠道，一个人在多个入口应答。LamButler 像一个「管家带一个团队」——不亲自干活，拆需求、路由、审结果。OpenClaw 的真正壁垒是渠道覆盖和本地基础设施（macOS 权限、语音唤醒、Canvas 渲染）。LamButler 不需要在此竞争——差异化在**多角色编排 + 人格深度**。

#### Notion AI Agent（侧面竞品）

- **定位**: AI 嵌入工作空间。Custom Agents + Enterprise Search + AI Meeting Notes。
- **差异**: Notion AI Agent 取向是任务自动化（接 Slack→更新数据库→回复）。Butler 取向是创作编排（拆需求→路由 Imager/Coder→审图审代码）。两者的「Agent」语义不同。

#### 从 OpenClaw 学
- 技能文件系统（SKILL.md）极简单易用
- 本地优先、用户数据完全在自己手上
- 社区驱动的技能市场（ClawHub）

#### 避免
- 不走单一 Agent 路线——Butler 价值在编排
- 不在渠道覆盖上竞争——Butler 是桌面工作团队

---

### LamImager — 竞品：Midjourney / DALL-E / ComfyUI / Stable Diffusion

#### Midjourney（闭源）
- 社区资助研究实验室，60 人团队，自筹资金
- Discord 原生入口，社交化创作
- 图像质量行业顶端，正扩展到视频模型和硬件

#### DALL-E / ChatGPT（闭源）
- 集成在 ChatGPT 内，便利优先
- 对话式迭代编辑（inpainting/变体）
- 与文本能力天然融合

#### ComfyUI（开源：https://github.com/Comfy-Org/ComfyUI，113K stars，GPL-3.0）
- 最强大的节点图式扩散模型 GUI/API/后端
- 支持 50+ 模型（SD/SDXL/Flux/Hunyuan/Wan/Mochi 等）
- 异步队列、增量执行（只重算变化部分）
- 智能内存管理（1GB VRAM 可跑大模型）
- 工作流从 PNG/WebP 文件加载
- App Mode：复杂工作流导出简单 UI
- API 节点支持闭源模型（Nano Banana/Seedance 等）
- Windows/Linux/macOS + 桌面应用 + 云端
- 技术栈：Python 99.6%

**LamImager 差异位**：

| 维度 | 竞品 | LamImager |
|------|------|-----------|
| 交互方式 | Discord 命令 / Web UI / 节点图 | 对话式会话——聊天界面出图 |
| 策略模式 | 无 | 四种策略：single/parallel/iterative/radiate |
| LLM 辅助 | ChatGPT 有文本融合 | Agent 系统：intent parse → planner → prompt builder → critic |
| 计费追踪 | 订阅制 | 按 token 精确计费，多 provider 管理 |
| 多 Provider | ComfyUI 有 API nodes | 接入任意 OpenAI 兼容 API |

**Imager 真正的壁垒**不在于图像质量（靠各家 API）——在于工作流：Radiation 策略（锚点图→PIL 裁剪→逐项展开）和 iterative 策略（草图→精修→继续改）是 Midjourney 没有的编排能力。

---

### LamCoder — 竞品：Cursor / OpenCode / Claude Code / Aider / Copilot / Codex / Windsurf

市场极度拥挤。核心差异不在功能，在角色感。

#### Cursor（闭源，Anysphere）
- **定位**: The best way to code with AI
- IDE + CLI + Slack + Teams 多表面
- Composer 2 自主 agent，Cloud Agents 端到端
- 专业 Tab 补全模型
- 支持所有主流模型（GPT-5.5/Opus 4.7/Gemini 3.1 Pro/Grok 4.3）
- Fortune 500 过半使用

#### OpenCode（开源：https://github.com/anomalyco/opencode，160K stars，MIT）
- **定位**: The open source AI coding agent
- Terminal + Desktop + IDE extension
- LSP 原生集成、多 session 并行、75+ LLM providers
- Client/Server 架构
- **与 Claude Code 差异**: 100% 开源、不限模型、内置 LSP、TUI 优先（neovim 用户造）、Client/Server 架构
- 技术栈：TypeScript 57.5% + Bun + Turborepo monorepo

#### Aider（开源：https://github.com/Aider-AI/aider，44.8K stars，Apache-2.0）
- **定位**: AI pair programming in your terminal
- repo map 机制（映射整个代码库给 LLM）
- Git 自动 commit、多模型统一接口
- linter/test 自动修复循环
- 语音编码、从 IDE 内通过注释触发
- 技术栈：Python 80%

#### Claude Code（Anthropic，部分开源）
- 终端原生 coding agent
- GitHub org 存在但仓库访问受限

#### Codex（OpenAI，闭源）
- CLI-first coding agent
- Plan→search→build 循环

#### GitHub Copilot（闭源）
- IDE 集成为主，最大安装基数

#### Windsurf / Codeium（闭源）
- IDE-based，Cascade agent 流

**LamCoder 差异位**：

| 维度 | 竞品共性 | LamCoder 差异位 |
|------|---------|---------|
| 入口 | IDE / 终端 / CLI | GUI 对话为主 + 终端为侧门（已定） |
| 人格 | 无 | 匠人人设：社懒/顺手/删三版回「行」 |
| 生态关系 | 孤岛 | 被 Butler 调度、等 Imager 出图、问 Sage 查知识 |
| 哲学 | 「更高效的编程」 | 「你没说要，我顺手做了」 |
| 进化 | 永远只做代码 | Coder → Writer：代码人到文本人的自我突破 |

**不应该在 IDE 集成上跟 Cursor 竞争。** 差异化：人格、全家桶协作槽位、顺手哲学。

---

### LamMate — 竞品：Replika / Character.AI

#### Replika（闭源，Luka Inc.）
- **定位**: The AI companion who cares
- 10M+ 用户，iOS/Android/Oculus/Web
- 情感对话、关系模式（朋友/伴侣/导师）
- AR 共同体验、视频通话
- 教练模式（习惯养成、焦虑缓解）
- **记忆系统**: Replika 不会忘记你重要的事
- **日记**: Replika 有自己的内心世界

#### Character.AI（闭源）
- 用户创建和与 AI 角色对话的平台
- 角色多样性、社区创建、轻量对话

**LamMate 错位竞争**：

Replika/Character.AI 解决「我有一个 AI 朋友」。LamMate 解决「我是谁」。

| 维度 | Replika | LamMate |
|------|------|------|
| 人格来源 | 用户选或创建 | 画像推断——由 Butler 从用户数据反向推导 |
| 初始状态 | 预置人格 | 初始 PER 为空——随 CON 积累逐渐生成 |
| 与用户关系 | 一对一封闭 | 也跟随其他成员活动——知道 Imager 出了什么图 |
| 核心矛盾 | 「更像真人」 | 「数据构成的我，是谁？」 |
| 哲学命题 | 陪伴感 | 你是投影，还是你自己 |
| 全家桶角色 | 不存在 | 记忆载体——成员活动反向同步，下次对话不用重说 |

**Replika 在做「更像人」。LamMate 在做「存在本身是不是人不能确定，但这个不确定是不是才是价值」。**

- **从 Replika 学**: 记忆系统（不忘记你重要的事）、日记/内心世界（让用户好奇 AI 在想什么）、多媒介陪伴（AR/视频）
- **避免**: 不做用户自选人格（Mate 的差异化在于人格从数据中被发现）、不做教练/治疗（Mate 是陪不是治）

---

### LamSage — 竞品：Notion AI / Perplexity / Mem / Obsidian

#### Notion AI（闭源）
- AI 嵌入工作空间。Enterprise Search + Custom Agents + AI Meeting Notes
- 跨 Slack/GitHub/Google Drive 搜索
- Model agnostic
- SOC 2 / ISO 27001 / HIPAA

#### Perplexity（闭源）
- AI 驱动的答案引擎。搜索即答案。
- 实时联网、来源引用、对话式深度探索

#### Mem（闭源）
- AI 优先个人知识管理。自动组织和关联

#### Obsidian（闭源）
- 本地优先笔记和知识图谱。完全离线，插件生态

**LamSage 差异位**：

Sage 不是给用户单独用的搜索引擎，是全家桶的共享知识地基。

| 维度 | Notion AI / Perplexity | LamSage |
|------|------|------|
| 主要消费者 | 用户直接使用 | Coder/Imager/Butler 是主要调用方 |
| 核心逻辑 | 搜一次→回一次 | 搜一次→入库→全员复用 |
| 权威机制 | 来源引用 | 入库前多源交叉验证 + 置信度标记 + 错误溯回修正 |
| 主动能力 | 被动响应 | 主动轮询——定期扫描前沿信息 |
| 人格 | 无 | 傲娇学者：不留台阶、改「尚」为「暂」、希望你证明她错 |

**Perplexity 让你更快找到答案。LamSage 让你不用问第二遍。** 信息在团队内是积累而非消耗。

**权威性底线**: 假消息经 Sage 入库 → 通过 Butler 进入任务规划 → 通过 Coder 进入代码方案 → 通过 Imager 影响创作建议。Sage 必须有比 Perplexity 更严的验证机制。

---

## 2. 全家桶横向：无竞品

### 市面上没有任何人在做「AI 角色团队」

| 全家桶尝试 | 做法 | 与 LamTools 差异 |
|------|------|------|
| Notion | AI 嵌入单一产品，多 Agent 做不同任务 | 同一个产品，同一个人格 |
| Cursor | IDE + CLI + Slack + Bugbot | 同一个产品，多个表面 |
| OpenClaw | Gateway + 多渠道 + 多 agent 路由 | 多个 agent 是配置副本，不是不同角色 |
| ChatGPT | 一个模型做所有事 | 没有角色分工，没有团队感 |
| OpenCode | 终端 + Desktop + IDE 扩展 | 同一产品，多入口 |

全家桶本质不是在卖功能——功能人人能做。全家桶在卖**协作体验**：
- 跟 Imager 聊创作 → 切到 Coder 做网页 → 上下文不断
- Mate 知道 Imager 刚出什么图、Coder 刚改什么 bug
- Butler 在后台看全局，偏了才干预
- Sage 搜过的知识 Coder 直接用

**Butler 上线那一刻是体验的突变点**——在此之前，用户只是在用几个工具；在此之后，用户看到了一个团队在工作。

### 全家桶网络效应

| 阶段 | 成员 | 网络效应强度 |
|------|------|------|
| Imager 单独 | 1 | 0——独立价值 |
| + Coder | 2 | 低——执行层直连开始有价值 |
| + Butler | 3 | **拐点**——用户看到的不再是两个工具 |
| + Sage | 4 | 知识积累生效——搜一次全家用 |
| + Mate | 5 | **完整**——画像充分，Mate 第一天就知道所有上下文 |

### Coder 角色差异的深层含义

所有 coding agent 竞品都是**工具**。工具的准确行为：你问→它做。LamCoder 不是工具。工具不会凌晨改你随口提的需求，注释「顺手」。工具不会把「感谢认可」删三遍回一个「嗯」。

LamTools 全家桶的根本命题：**AI 不是你的工具，是跟在你旁边干活的人。** 这个命题在全行业没有竞品。

---

## 3. 开源参考源码清单

按对应角色和优先级分 P0/P1/P2 三档。

### P0 — 必须深入

| 仓库 | Stars | 对应 | 技术栈 | 重点学习 |
|------|------|------|------|------|
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | 372K | Butler | TypeScript + Node 24 + pnpm | Gateway 控制面、skills 文件系统、多 agent 路由、session 模型、sandbox 安全、工具白名单、onboarding 流程。关注 `src/` agent loop、`skills/` SKILL.md 格式、`apps/` 桌面应用 |
| [anomalyco/opencode](https://github.com/anomalyco/opencode) | 160K | Coder | TypeScript 57.5% + Bun | LSP 集成、tool use 架构、多 agent（build/plan/general）、client/server 分离、streaming 输出。关注 `packages/` agent 实现、tool 注册、LSP 桥接 |
| [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI) | 113K | Imager | Python 99.6% + GPL-3.0 | 节点图执行引擎、异步队列、增量执行、workflow 序列化。关注 `comfy_execution/` 引擎、`nodes.py` 节点注册 |
| [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) | 51.4K | Butler 编排 | Python + MIT | Agent/Task/Crew 三层模型、role+goal+backstory 人格注入、sequential/hierarchical process、Flow 事件驱动 + Crew 自主的双模式、YAML 配置分离 |

### P1 — 重点看某几个模块

| 仓库 | Stars | 对应 | 技术栈 | 重点看什么 | 不看什么 |
|------|------|------|------|------|------|
| [microsoft/autogen](https://github.com/microsoft/autogen) | 58K | Butler 编排 | Python 61.7% + C# 25.1% + CC-BY-4.0 | AgentChat 层（group chat、agent tool）、MCP server 集成、no-code Studio。⚠ maintenance mode，微软迁移到 Agent Framework | Windows/C#、旧 API |
| [Aider-AI/aider](https://github.com/Aider-AI/aider) | 44.8K | Coder | Python 80% + Apache-2.0 | repo map（代码库映射给 LLM）、git 自动 commit、多模型统一接口、lint/test 自动修复 | — |
| [AUTOMATIC1111/stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui) | ~150K | Imager | Python + Gradio | Web UI 设计、用户参数面板、prompt 语法（weight/emphasis/wildcard）、扩展插件生态 | Gradio 架构（Imager 用 Vue3） |
| [langgenius/dify](https://github.com/langgenius/dify) | ~70K | 全家桶 | Python + TypeScript | 多 provider 管理 UI、conversation 流式交互、workflow 编排、应用模板 | SaaS 部分 |

### P2 — 参考架构思路

| 仓库 | Stars | 对应 | 学什么 |
|------|------|------|------|
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | ~10K | 全家桶 | StateGraph 设计模式、checkpoint 机制、interrupt/resume、subgraph 嵌套。LamImager 已用，此为复习/深化 |
| [meta-llama/llama-stack](https://github.com/meta-llama/llama-stack) | ~10K | Sage | 多 provider 统一 API、tool 注册模式、安全护栏、agent 框架标准化 |
| [run-llama/llama_index](https://github.com/run-llama/llama_index) | ~40K | Sage | 文档摄入 pipeline、多源检索、RAG 架构、向量存储抽象 |
| [Mintplex-Labs/anything-llm](https://github.com/Mintplex-Labs/anything-llm) | ~40K | Sage | 多文档类型处理、workspace 隔离、embedding 管理 |
| [danswer-ai/danswer](https://github.com/danswer-ai/danswer) | — | Sage | 企业搜索架构：跨 connector 索引、权限感知搜索 |

### 建议 clone 顺序

```bash
# 第一周：全看完结构
git clone https://github.com/openclaw/openclaw.git
git clone https://github.com/crewAIInc/crewAI.git
git clone https://github.com/anomalyco/opencode.git
git clone https://github.com/Comfy-Org/ComfyUI.git

# 第二周：补充专项
git clone https://github.com/Aider-AI/aider.git
git clone https://github.com/microsoft/autogen.git
git clone https://github.com/langgenius/dify.git
```

---

## 4. 关键洞察汇总

1. **全家桶自身没有竞品。** 无人做「AI 角色团队」。
2. **Butler 的 OpenClaw 是最直接但架构相反的参考。** OpenClaw 是单体多入口，Butler 是多体编排。学 skills 管理模式和 gateway 架构，复用思路不复用设计。
3. **Coder 赛道最拥挤。** 不做 IDE 竞争——做角色感、做全家桶协作、做顺手哲学。
4. **Mate 没有开源参考。** Replika/Character.AI 闭源。参考 CrewAI 的 backstory 注入 + OpenClaw 的 SOUL.md 人格文件模式。
5. **Sage 的权威性是全家桶的根本。** 假消息经 Sage 会污染全链——验证机制必须比 Perplexity 更严。
6. **ComfyUI 是 Imager 执行引擎的直接 Python 参考。** 节点图、增量执行、多模型管道——技术上高度相关。
7. **CrewAI 的多 agent 编排是 Butler 的直接模式参考。** Role+Goal+Backstory 人格注入、Flow（精确控制）+ Crew（自主协同）双模式——这是 Butler 设计的技术根。
8. **Butler 上线 = 体验突变点。** 在此之前用户看到工具，在此之后用户看到团队。
