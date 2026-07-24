# LamTools

## 项目结构

- **Core** (`core/`)：Agent 基座，一个基础独立可用的 Agent。
- **Member** (`members/`)：基于 Core 在各领域适配的专家。当前有 Writer 与 Sage。

## 核心规则

- 没有明确要求时，改动在 `core/` 内进行，并正确继承给所有 member。
- 改动 member 功能前，先询问是否需要下沉到 `core/`。
- 任何 GUI 能力必须有对应的 CLI。
- PowerShell 涉及中文必须使用 UTF-8。

## 开发启动

```powershell
.\scripts\dev.ps1 core              # Core 前后端 (5172 / 5173)
.\scripts\dev.ps1 writer            # Writer (6173 / 6174)
.\scripts\dev.ps1 sage              # Sage (6170 / 6171)
.\scripts\dev.ps1 all               # 全部
```
