# LamTools

LamTools monorepo — 当前聚焦 Core 建设。所有开发、构建、文档均在此仓库完成。

## 目录结构

```
LamTools/
├── core/              ← Core（协议层、主循环骨架、共享 UI 组件）—— 唯一活跃产品
├── archive/members/   ← 已归档的 member 产品（Writer / Sage / Imager），保留历史，不再维护
├── docs/              ← 仓库级文档
├── scripts/           ← Core 维护脚本
└── .gitignore
```

## 组件概览

| 组件 | 路径 | 说明 | 技术栈 |
|------|------|------|--------|
| Core | `core/` | 通用协议、类型、Core Loop Kernel、共享 UI Shell、独立可用的 Agent | Python 3.14+ / FastAPI / Vue3 / TypeScript |

Member 产品（Writer / Sage / Imager）已归档至 `archive/members/`，保留完整提交历史可追溯，不再维护。后续如需重启 member，从当前 Core 基座重新接入。

## 开发

| 命令 | 用途 |
|------|------|
| `.\scripts\dev.ps1 core all` | 启动 Core 开发服务器（前后端） |
| `.\scripts\build.ps1 all` | 构建 Core 前端 |
| `.\scripts\test.ps1 all` | 运行 Core 测试 |

Core 的细分命令见 `core/README.md`。

## 迁移记录

早期成员曾通过 `git subtree add` 从独立仓库迁入，完整提交历史仍保留在 Git 中。Member 产品已于 2026-08 归档至 `archive/members/`，工作树只维护 Core。详见 [docs/monorepo-migration.md](docs/monorepo-migration.md)。

## License

[MIT](LICENSE) © 2026 Lam (Laaaaaaaam)
