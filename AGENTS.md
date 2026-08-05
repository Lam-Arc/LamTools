# LamTools

## 项目结构

- **Core** (`core/`)：Agent 基座，一个基础独立可用的 Agent。当前唯一活跃产品。
- **Archive** (`archive/members/`)：已归档的 member 产品（Writer / Sage / Imager），保留历史可追溯，不再维护。

## 核心规则

- 当前聚焦 Core 建设，所有改动在 `core/` 内进行。
- 任何 GUI 能力必须有对应的 CLI。
- PowerShell 涉及中文必须使用 UTF-8。

## 开发启动

```powershell
.\scripts\dev.ps1 core              # Core 前后端 (5172 / 5173)
.\scripts\dev.ps1 all               # 同上（Core-only）
.\scripts\restart.ps1               # 重启 Core 前后端
```

## 数据库

| 组件 | 路径 |
|------|------|
| Core | `data/core.db` |
