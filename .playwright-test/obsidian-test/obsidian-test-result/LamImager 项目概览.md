# LamImager 项目概览

> 状态：✅ 有效 | 来源：README.md, AGENTS.md, CHANGELOG.md

## 是什么

LamImager 是一个 AI 图像生成管理器——全栈桌面应用，支持 AI 驱动图像生成、对话式界面、LLM 规划与实时流式输出。它是 [[LamTools 生态设计]]中的图像/视觉成员，也是 LamTools 的前身项目。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.14+ / FastAPI / SQLAlchemy (async) / aiosqlite |
| 前端 | Vue3 / TypeScript / Pinia / Vue Router / Vite |
| 桌面端 | PyInstaller + pywebview (Windows) |
| 数据库 | SQLite (单文件) |
| AI | LangGraph StateGraph |
| UI | Lucide 图标，黑白灰配色 |

## 核心功能

- **对话式生图**：聊天界面，支持会话管理、参考图上传、精修模式
- **Artist 智能模式**：Runtime 驱动的创作 loop，自动识别意图、规划、执行、审查
- **四种生成策略**：single / parallel / iterative / radiate（锚点网格→裁切→逐项展开）
- **Lineage DAG**：图像谱系树，支持分支、HEAD 切换、回滚（git 语义）
- **LLM 侧边栏助手**：提示词优化、规划、自由对话
- **计费追踪**：按 token / 按调用精确计费，多 provider 管理
- **API 密钥加密**：AES-256-GCM

## 版本历史

| 版本 | 日期 | 关键变更 |
|------|------|---------|
| 0.1.0 | 2026-05-10 | 初始发布：会话 UI、API 管理、Agent 模式、提示词优化 |
| 0.2.0 | 2026-05-11 | Agent 支持参考图、多模态推理、混合意图解析 |
| 0.2.1 | 2026-05-11 | Plan 执行器、模板验证 |
| 0.3.1 | 2026-05-11 | API vendor 层、密钥派生改为文件种子 |
| 0.3.2 | 2026-05-12 | 多模态上下文修复 |
| 0.4.0 | 2026-05-12 | P2 LangGraph 集成：8 节点图、critic/decision、checkpoint |
| 0.4.1 | 2026-05-13 | 9 节点图、skill_matcher、全链路计费、10 个数据流 bug 修复 |
| 0.4.2 | 2026-05-16 | ImageContextResolver、统一执行引擎、Agent 内联显示 |

## 项目结构

```
LamImager/
├── backend/app/          # FastAPI 后端
│   ├── core/agent/       # LangGraph 图 + 节点
│   ├── core/artist/      # Artist Runtime（loop/tool/schemas/events）
│   ├── services/         # 业务逻辑（generate/artist/lineage/billing...）
│   ├── routers/          # 11 个路由模块
│   ├── models/           # 10 张表
│   └── utils/            # crypto/llm_client/image_client
├── frontend/src/         # Vue3 前端
│   ├── views/            # WorkbenchView + SettingsView
│   ├── stores/           # Pinia（session/provider/billing）
│   └── components/session/  # 图片/谱系/灯箱等
├── desktop/              # PyInstaller + pywebview
└── docs/                 # 架构、API、运维、计划
```

## 关联

- 架构细节 → [[LamImager 架构设计]]
- 认知模型 → [[LamImager 心智模型]]
- 开发历程 → [[LamImager 开发路线图]]、[[LamImager 进度日志]]
- 生态定位 → [[LamTools 生态设计]]
