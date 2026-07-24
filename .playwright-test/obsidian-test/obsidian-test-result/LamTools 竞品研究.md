# LamTools 竞品研究

> 状态：✅ 有效 | 来源：competitive-research.md
>
> 2026-05-15 存档。五产品竞品分析和开源参考源码清单。

## 竞品格局

### LamButler — 最接近对手：OpenClaw

| 维度 | OpenClaw | LamButler |
|---|---|---|
| 架构 | 单 Agent + 多入口 | 多 Agent 编排中心 |
| 核心理念 | 一个助手走天下 | 一个管家调度一个团队 |
| 角色深度 | 吉祥物（浅层） | 完整人设 |
| 干预机制 | 用户手动控制 | 三路径干预 + 评价三档 |

> OpenClaw 解决问题像「一个律师」，LamButler 像「管家带一个团队」。差异化在多角色编排 + 人格深度。

### LamImager — 竞品：Midjourney / DALL-E / ComfyUI

Imager 真正的壁垒不在图像质量（靠各家 API），在于工作流：Radiation 策略和 iterative 策略是 Midjourney 没有的编排能力。

### LamCoder — 赛道最拥挤

竞品：Cursor / OpenCode / Claude Code / Aider / Copilot / Codex / Windsurf

> 不应该在 IDE 集成上跟 Cursor 竞争。差异化：人格、全家桶协作槽位、顺手哲学。

### LamMate — 竞品：Replika / Character.AI

> Replika 在做「更像人」。LamMate 在做「数据构成的我，是谁？」

### LamSage — 竞品：Notion AI / Perplexity / Obsidian

> Perplexity 让你更快找到答案。LamSage 让你不用问第二遍。

## 全家桶横向：无竞品

市面上没有任何人在做「AI 角色团队」。全家桶在卖**协作体验**，不是功能。

Butler 上线那一刻是体验的**突变点**——此前用户看到工具，此后用户看到团队。

## 开源参考源码

### P0 — 必须深入

| 仓库 | Stars | 对应 | 重点学习 |
|---|---|---|---|
| openclaw/openclaw | 372K | Butler | Gateway、skills、多 agent 路由、sandbox |
| anomalyco/opencode | 160K | Coder | LSP 集成、tool use、client/server 分离 |
| Comfy-Org/ComfyUI | 113K | Imager | 节点图执行引擎、异步队列、增量执行 |
| crewAIInc/crewAI | 51.4K | Butler 编排 | Agent/Task/Crew 三层、人格注入 |

### P1 — 重点看某几个模块

| 仓库 | 对应 | 重点 |
|---|---|---|
| microsoft/autogen | Butler | AgentChat、MCP 集成（⚠ maintenance mode） |
| Aider-AI/aider | Coder | repo map、git 自动 commit |
| AUTOMATIC1111/stable-diffusion-webui | Imager | Web UI、prompt 语法、扩展生态 |
| langgenius/dify | 全家桶 | 多 provider 管理、workflow 编排 |

### P2 — 参考架构思路

| 仓库 | 对应 | 学什么 |
|---|---|---|
| langchain-ai/langgraph | 全家桶 | StateGraph、checkpoint、interrupt/resume |
| meta-llama/llama-stack | Sage | 多 provider 统一 API、安全护栏 |
| run-llama/llama_index | Sage | 文档摄入、RAG、向量存储 |
| Mintplex-Labs/anything-llm | Sage | 多文档类型、workspace 隔离 |

## 关键洞察

1. 全家桶自身没有竞品
2. Butler 的 OpenClaw 是最直接但架构相反的参考
3. Coder 赛道最拥挤——做角色感、全家桶协作、顺手哲学
4. Mate 没有开源参考
5. Sage 的权威性是全家桶的根本——假消息会污染全链
6. ComfyUI 是 Imager 执行引擎的直接 Python 参考
7. CrewAI 的多 agent 编排是 Butler 的直接模式参考
8. Butler 上线 = 体验突变点

## 关联

- 生态设计 → [[LamTools 生态设计]]
- 源码调研 → [[LamImager 源码调研报告]]
- 成员架构 → [[LamTools 成员架构设计]]
