# LamTools

LamTools monorepo — 统一维护入口。所有开发、构建、文档均在此仓库完成。

## 目录结构

```
LamTools/
├── core/              ← Core SDK + UI Core（协议层、主循环骨架、共享 UI 组件）
├── members/
│   ├── writer/        ← Writer 产品（AI 工程与写作伴侣）
│   └── sage/          ← Sage 产品（信息搜集、数据处理与置信验证）
├── docs/              ← monorepo 级文档
├── scripts/           ← 跨组件脚本
└── .gitignore
```

## 组件概览

| 组件 | 路径 | 说明 | 技术栈 |
|------|------|------|--------|
| Core | `core/` | 通用协议、类型、Core Loop Kernel、共享 UI Shell | Python 3.14+ / FastAPI / Vue3 / TypeScript |
| Writer | `members/writer/` | AI 工程与写作伴侣，CoreLoopKernel + WriterKit 架构 | Python 3.14+ / FastAPI / Vue3 / TypeScript |
| Sage | `members/sage/` | 证据优先的研究、验证、关系整理与持续关注 Agent | Python 3.14+ / FastAPI / Vue3 / TypeScript |

当前活跃产品成员为 Writer 与 Sage。未来新增成员必须从当前 Core 基座和脚手架重新接入，不继承已下线成员的旧运行链路。

## 开发

| 命令 | 用途 |
|------|------|
| `.\scripts\build.ps1 all` | 构建全部前端 |
| `.\scripts\dev.ps1 writer all` | 启动 Writer 开发服务器（前后端） |
| `.\scripts\dev.ps1 sage all` | 启动 Sage 开发服务器（前后端） |
| `.\scripts\test.ps1 all` | 运行全部测试 |

各组件的细分命令见其目录下的 README / AGENTS.md：

- Core：`core/README.md`
- Writer：`members/writer/AGENTS.md`
- Sage：`members/sage/README.md`

## 添加新成员

使用脚手架脚本一键生成新成员目录：

```powershell
.\scripts\scaffold-member.ps1 -Id editor -Name LamEditor -DisplayName LamEditor -Capabilities code,git           # 实际生成
.\scripts\scaffold-member.ps1 -Id editor -Name LamEditor -DisplayName LamEditor -Capabilities code,git -DryRun  # 预览不写入
```

脚本从 `core/templates/member/` 模板复制并替换占位符（`__MEMBER_ID__`、`__MEMBER_NAME__`、`__DISPLAY_NAME__`、`__KEBAB_NAME__`、`__BACKEND_PORT__`、`__FRONTEND_PORT__`、`__ENV_PREFIX__`、`__CAPABILITIES_JSON__`），生成最小可运行的 backend + frontend 骨架。详见 `core/docs/new-member-core-onboarding.md`。

## 迁移记录

早期成员曾通过 `git subtree add` 从独立仓库迁入，完整提交历史仍保留在 Git 中。当前工作树只维护 Core + Writer。详见 [docs/monorepo-migration.md](docs/monorepo-migration.md)。
