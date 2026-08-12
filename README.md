# 🧠 LamTools — Local-first AI Agent Framework

> **本地优先的 AI Agent 框架** · DeepSeek 兼容 · 开箱即用的桌面应用

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-0.2.2-green.svg)](https://github.com/Lam-Arc/LamTools/releases)
[![Stars](https://img.shields.io/github/stars/Lam-Arc/LamTools.svg?style=social)](https://github.com/Lam-Arc/LamTools)

**LamTools** 是一个 **local-first（本地优先）的 AI Agent 框架**：你的对话、会话、任务、工具调用全部跑在**你自己的电脑**上，数据不出本地，模型随便换。

内置 **DeepSeek（`deepseek-v4-pro` / `deepseek-v4-flash`）**、OpenAI、Claude/Anthropic、智谱 GLM、讯飞 Coding 等主流模型预设，一个配置文件即可切换。

---

## ✨ 特性

- 🏠 **Local-first** — 数据全部落在本地 SQLite，无需注册、无需云账号，断网也能管理你的会话
- 🔌 **DeepSeek 兼容** — 内置 DeepSeek 官方预设（`deepseek-v4-pro` / `deepseek-v4-flash`），OpenAI 兼容 API，改一行配置即可接入
- 🤖 **能力委派（sub-agent）** — 主模型不支持的输入（图片/音频/文档）自动委派给支持多模态的子代理分析，子代理独立会话、按需指定模型
- 🧩 **多模型即插即用** — OpenAI / Claude / GLM / 讯飞 / OpenCode Zen 预设，支持自定义 provider
- 🧠 **Core Loop Kernel** — 事件驱动的 Agent 主循环：LLM 调用 → 工具执行 → 校验 → 决策，可插拔的 Kit 架构
- 🛠 **工具系统** — 内置文件、Git、Web 搜索、MCP 等工具，带细粒度审批（auto-allow / ask-user / deny）
- ⏰ **长期任务（Arrange）** — 跨会话的持久任务调度：focus / routine 两种模式，崩溃自动恢复
- 📦 **桌面应用** — Windows 原生安装包（NSIS），前端 + 后端一键打包，免装 Python 环境
- 🎨 **现代 UI** — Vue 3 + TypeScript 工作台：会话、舞台、审批、设置面板一应俱全

---

## 🔌 DeepSeek 集成

LamTools 内置 **DeepSeek 官方预设**，开箱即用：

| 模型 | 说明 |
|------|------|
| `deepseek-v4-pro` | DeepSeek-V4-Pro（最新旗舰，强推理）|
| `deepseek-v4-flash` | DeepSeek-V4-Flash（快速响应，低成本）|

```jsonc
// .lam/core/config/providers.jsonc
{
  "providers": [
    {
      "id": "deepseek",
      "baseUrl": "https://api.deepseek.com",
      "apiKey": "sk-你的密钥",
      "models": ["deepseek-v4-pro", "deepseek-v4-flash"]
    }
  ]
}
```

或者直接在设置面板里选 **DeepSeek** 预设，填入 API Key 即可。

### 🤖 能力委派：让不支持的功能交给子代理

DeepSeek 等**纯文本模型不支持图片输入**？没关系——LamTools 的 **sub-agent 委派机制**会在主模型能力不足时，把图片/音频/文档等附件**转发给运行着支持多模态模型的子代理**完成分析：

```
你发一张图给 DeepSeek（不支持看图）
        ↓
LamTools 检测到主模型不支持多模态
        ↓
委派给子代理（如 Claude、GPT-4.1 等多模态模型）
        ↓
子代理分析图片 → 结果回传给主对话
```

- **主模型专注推理**，多模态任务由子代理分担
- **按需指定子代理模型**（更强推理 / 更长上下文 / 多模态能力）
- 子代理支持**独立会话**，后续追问自动续接上下文

```jsonc
// 在会话中通过 sub-agent 工具指定
{
  "task": "分析这张图片的内容",
  "agent": "vision-assistant",
  "model": "gpt-4.1",           // 指定多模态模型
  "attachments": ["img_001"]     // 转发图片附件
}
```

---

## 🧠 架构

```
┌─────────────────────────────────────────────────────┐
│                    LamTools Desktop (Tauri)          │
│  ┌───────────────────────────────────────────────┐  │
│  │              Vue 3 + TypeScript UI             │  │
│  │   SessionSidebar │ ChatThread │ RuntimePanel  │  │
│  └──────────────────────────┬────────────────────┘  │
│                             │ WebSocket / REST      │
│  ┌──────────────────────────▼────────────────────┐  │
│  │          lamtools_core (FastAPI)               │  │
│  │  ┌──────────────┐  ┌──────────────────────┐   │  │
│  │  │ Core Loop    │  │ Operation Catalog    │   │  │
│  │  │ Kernel       │  │ (RPC / WS / REST)    │   │  │
│  │  └──────┬───────┘  └──────────┬───────────┘   │  │
│  │         │                     │                │  │
│  │  ┌──────▼─────────────────────▼───────────┐   │  │
│  │  │  LLM 适配层 (OpenAI/DeepSeek/Claude…)  │   │  │
│  │  │  工具系统 (文件/Git/Web/MCP)           │   │  │
│  │  │  持久化 (SQLite: 会话/快照/Arrange)    │   │  │
│  │  └───────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

- **Core**（`core/`）：Agent 基座 — LLM 适配、工具、会话、审批、Checkpoint、Arrange 调度
- **桌面端**（`core/desktop/`）：Tauri 原生壳 + PyInstaller 打包后端
- **UI**（`core/ui/`）：Vue 3 共享工作台

---

## 🚀 快速开始

### 方式一：桌面安装包（推荐）

从 [Releases](https://github.com/Lam-Arc/LamTools/releases) 下载 `LamCore_*-setup.exe`，双击安装，**免装 Python / Node 环境**。

### 方式二：从源码运行

```bash
# 1. 克隆
git clone https://github.com/Lam-Arc/LamTools.git
cd LamTools

# 2. 安装依赖（Python 3.14+ / Node 20+）
pip install -r core/requirements.txt
cd core/ui && npm install && cd ../..

# 3. 启动开发服务器
.\scripts\dev.ps1 core all
# 打开 http://127.0.0.1:5173
```

### 配置模型

启动后打开设置面板，选择 provider（DeepSeek / OpenAI / Claude / GLM…），填入 API Key 即开始对话。

---

## 📂 仓库结构

```
LamTools/
├── core/                  ← Core 基座（唯一活跃产品）
│   ├── src/lamtools_core/  ← Python Agent 内核
│   ├── ui/                 ← Vue 3 工作台
│   └── desktop/            ← Tauri 桌面壳
├── archive/members/       ← 已归档产品（Writer/Sage/Imager）
├── docs/                  ← 文档
└── scripts/               ← 维护脚本
```

---

## 🗺 Roadmap

- [x] Core Loop Kernel（主循环）
- [x] DeepSeek / OpenAI / Claude 多模型预设
- [x] 桌面安装包（Tauri + NSIS）
- [x] Arrange 长期任务调度
- [ ] 多用户协作会话
- [ ] 插件市场
- [ ] macOS / Linux 安装包

---

## 📜 License

[MIT](LICENSE) © 2026 Lam (Laaaaaaaam)

---

## 🌟 支持我们

如果 LamTools 对你有帮助，请点个 ⭐ Star —— 你的支持是我们持续开发的动力！
