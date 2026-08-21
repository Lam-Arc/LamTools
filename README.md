## 支持项目

如果 LamTools 对你有帮助，欢迎点 Star 支持喵！不点会哈气喵！

# LamTools

Local-first AI Agent framework. 本地优先的 AI Agent 框架，兼容 DeepSeek、OpenAI、Claude 等主流模型。

**[English](README.en.md) | 简体中文**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Stars](https://img.shields.io/github/stars/Lam-Arc/LamTools.svg?style=social)](https://github.com/Lam-Arc/LamTools)

---

## 核心卖点：给不会看图的模型装上眼睛

DeepSeek 等纯文本模型（V4-Pro / V4-Flash）不能直接看图片。LamTools 内置 sub-agent 能力委派机制：主模型遇到图片、音频、文档等不支持的输入时，自动把内容转发给支持多模态的子代理模型（Claude、GPT-4.1 等）完成分析，再把结果带回主对话。

```
用户发送图片给 DeepSeek（纯文本模型，无法看图）
        ↓
LamTools 检测到主模型不支持多模态输入
        ↓
委派给多模态子代理模型分析图片
        ↓
分析结果回传主对话，主模型继续推理
```

效果：文本模型负责推理，多模态模型负责看，各取所长，一条会话内无缝协作。

## 特性

- 模型即插即用：内置 DeepSeek（v4-pro / v4-flash）、OpenAI、Claude/Anthropic、智谱 GLM、讯飞 Coding、OpenCode Zen 预设，OpenAI 兼容 API 一行切换
- sub-agent 能力委派：多模态输入自动转发给支持它的子代理，子代理独立会话、按需指定模型
- 本地优先：对话、会话、任务、工具调用全部运行在本机，数据存本地 SQLite，无需注册、无需云账号
- Core Loop Kernel：事件驱动的 Agent 主循环（LLM 调用、工具执行、校验、决策），Kit 架构可插拔
- 工具系统：文件、Git、Web 搜索、MCP 等内置工具，细粒度审批（auto-allow / ask-user / deny）
- Arrange 长期任务：跨会话的持久任务调度（focus / routine），崩溃后自动恢复
- Windows 桌面应用：Tauri + PyInstaller 打包，安装包内置前后端，免装 Python / Node 环境

## DeepSeek 集成

内置 DeepSeek 官方预设，填入 API Key 即可使用：

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

也支持在设置面板中直接选择 DeepSeek 预设并填入密钥。多模态需求通过 sub-agent 委派机制自动处理，无需额外配置。

## 架构

```
LamTools Desktop (Tauri)
  Vue 3 + TypeScript 工作台
        |
    WebSocket / REST
        |
lamtools_core (FastAPI)
  Core Loop Kernel
  Operation Catalog (RPC / WS / REST)
  LLM 适配层 (DeepSeek / OpenAI / Claude / GLM)
  工具系统 (文件 / Git / Web / MCP)
  持久化 (SQLite: 会话 / 快照 / Arrange)
```

- Core（core/）：Agent 基座，LLM 适配、工具、会话、审批、Checkpoint、Arrange 调度
- 桌面端（core/desktop/）：Tauri 原生壳，PyInstaller 打包后端
- UI（core/ui/）：Vue 3 共享工作台

## 快速开始

方式一：从 Releases 下载 Windows 安装包（免装 Python / Node 环境）：

```
https://github.com/Lam-Arc/LamTools/releases
```

方式二：从源码运行

```bash
git clone https://github.com/Lam-Arc/LamTools.git
cd LamTools
pip install -e "core[desktop]"
cd core/ui && npm install && cd ../..
.\scripts\dev.ps1 core all
# 打开 http://127.0.0.1:5173
```

启动后在设置面板选择 provider（DeepSeek / OpenAI / Claude / GLM），填入 API Key 即可对话。

## 仓库结构

```
LamTools/
├── core/                    Core 基座（唯一活跃产品）
│   ├── src/lamtools_core/   Python Agent 内核
│   ├── ui/                  Vue 3 工作台
│   └── desktop/             Tauri 桌面壳
├── archive/members/         已归档产品（Writer / Sage / Imager）
├── docs/                    文档
└── scripts/                 维护脚本
```

## Roadmap

- Core Loop Kernel（主循环）
- DeepSeek / OpenAI / Claude 多模型预设
- Windows 桌面安装包（Tauri + NSIS）
- Arrange 长期任务调度
- 多用户协作会话（规划中）
- 插件市场（规划中）
- macOS / Linux 安装包（规划中）

## Research outputs / Citation

- Technical paper / preprint: [LamTools: 具备能力感知委派机制的本地优先 Agent 运行时](https://doi.org/10.5281/zenodo.22040870)
- Archived software release: [LamTools v0.2.6](https://doi.org/10.5281/zenodo.22039646)
- Citation metadata: [CITATION.cff](./CITATION.cff)

## License

MIT，Copyright (c) 2026 Lam (Laaaaaaaam)


