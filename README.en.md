## Support the project

If LamTools helps you, please Star the repo. Meow! 🐱

# LamTools

Local-first AI Agent framework. DeepSeek-compatible, multi-model (OpenAI / Claude / GLM / Xfyun), with a ready-to-run Windows desktop app.

**[简体中文](README.md) | English**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Stars](https://img.shields.io/github/stars/Lam-Arc/LamTools.svg?style=social)](https://github.com/Lam-Arc/LamTools)

---

## Core selling point: give eyes to models that cannot see images

Text-only models like DeepSeek (V4-Pro / V4-Flash) cannot understand images directly. LamTools has a built-in **sub-agent delegation** mechanism: when the main model encounters inputs it does not support (images, audio, documents), it automatically forwards the content to a multimodal sub-agent model (Claude, GPT-4.1, etc.) for analysis, then brings the result back into the main conversation.

```
User sends an image to DeepSeek (text-only model, cannot see images)
        ↓
LamTools detects the main model does not support multimodal input
        ↓
Delegates to a multimodal sub-agent model to analyze the image
        ↓
Result flows back to the main conversation, main model continues reasoning
```

The result: the text model handles reasoning, the multimodal model handles vision — each doing what it does best, collaborating seamlessly in one session.

## Features

- **Plug-and-play models**: built-in presets for DeepSeek (v4-pro / v4-flash), OpenAI, Claude/Anthropic, Zhipu GLM, Xfyun Coding, OpenCode Zen — switch with one line via the OpenAI-compatible API
- **Sub-agent capability delegation**: multimodal inputs are automatically forwarded to sub-agents that support them; sub-agents have independent sessions and on-demand model selection
- **Local-first**: conversations, sessions, tasks, and tool calls all run on your machine; data lives in local SQLite — no registration, no cloud account
- **Core Loop Kernel**: event-driven agent main loop (LLM call, tool execution, verification, decision) with a pluggable Kit architecture
- **Tool system**: built-in file, Git, web search, and MCP tools with fine-grained approval (auto-allow / ask-user / deny)
- **Arrange long-running tasks**: cross-session persistent task scheduling (focus / routine), auto-recovery after crashes
- **Windows desktop app**: packaged with Tauri + PyInstaller — the installer bundles frontend and backend, no Python / Node environment required

## DeepSeek integration

The official DeepSeek preset is built in — just fill in your API key:

```jsonc
// .lam/core/config/providers.jsonc
{
  "providers": [
    {
      "id": "deepseek",
      "baseUrl": "https://api.deepseek.com",
      "apiKey": "sk-your-key",
      "models": ["deepseek-v4-pro", "deepseek-v4-flash"]
    }
  ]
}
```

You can also pick the DeepSeek preset directly in the settings panel and enter your key. Multimodal needs are handled automatically by the sub-agent delegation mechanism — no extra configuration required.

## Architecture

```
LamTools Desktop (Tauri)
  Vue 3 + TypeScript workbench
        |
    WebSocket / REST
        |
lamtools_core (FastAPI)
  Core Loop Kernel
  Operation Catalog (RPC / WS / REST)
  LLM adapter layer (DeepSeek / OpenAI / Claude / GLM)
  Tool system (files / Git / Web / MCP)
  Persistence (SQLite: sessions / snapshots / Arrange)
```

- Core (`core/`): agent foundation — LLM adapters, tools, sessions, approvals, checkpoints, Arrange scheduling
- Desktop (`core/desktop/`): Tauri native shell, PyInstaller-packaged backend
- UI (`core/ui/`): Vue 3 shared workbench

## Quick start

Option 1: download the Windows installer from [Releases](https://github.com/Lam-Arc/LamTools/releases) (no Python / Node environment needed):

```
https://github.com/Lam-Arc/LamTools/releases
```

Option 2: run from source

```bash
git clone https://github.com/Lam-Arc/LamTools.git
cd LamTools
pip install -e "core[desktop]"
cd core/ui && npm install && cd ../..
.\scripts\dev.ps1 core all
# open http://127.0.0.1:5173
```

After startup, pick a provider in the settings panel (DeepSeek / OpenAI / Claude / GLM), fill in your API key, and start chatting.

## Repository layout

```
LamTools/
├── core/                    Core foundation (only active product)
│   ├── src/lamtools_core/   Python agent kernel
│   ├── ui/                  Vue 3 workbench
│   └── desktop/             Tauri desktop shell
├── archive/members/         Archived products (Writer / Sage / Imager)
├── docs/                    Documentation
└── scripts/                 Maintenance scripts
```

## Roadmap

- Core Loop Kernel (main loop)
- DeepSeek / OpenAI / Claude multi-model presets
- Windows desktop installer (Tauri + NSIS)
- Arrange long-running task scheduling
- Multi-user collaborative sessions (planned)
- Plugin marketplace (planned)
- macOS / Linux installers (planned)

## License

MIT, Copyright (c) 2026 Lam (Laaaaaaaam)
