# LamImager 运维参考

> 状态：⚠️ 可能过时 | 来源：runbook.md, api-reference.md, AGENTS.zh-CN.md, project_rules.md
>
> ⚠️ AGENTS.md 明确标注：api-reference.md / runbook.md 可能滞后于代码，使用前需对照源码验证。

## 开发环境

```bash
# 后端（Python 3.14+）
cd backend && py -3.14 -m uvicorn app.main:app --reload --port 6171

# 前端
cd frontend && npm run dev

# 桌面应用打包
py build.py [--clean] [--skip-frontend]
```

## API 端点概览

Base URL: `http://localhost:8000/api`（开发模式 6171）

| 模块 | 路径 | 说明 |
|---|---|---|
| 会话 | `/api/sessions/` | CRUD + generate + lineage |
| 消息 | `/api/sessions/{id}/messages` | 消息列表 |
| 供应商 | `/api/vendors/` | API 供应商 CRUD |
| 模型 | `/api/providers/` | 模型 CRUD |
| 计费 | `/api/billing/` | 记录/导出/统计 |
| 设置 | `/api/settings/` | 应用设置 |
| 技能 | `/api/skills/` | 技能 CRUD |
| 规则 | `/api/rules/` | 规则 CRUD |
| 计划模板 | `/api/plan-templates/` | 模板 CRUD |
| 健康检查 | `/api/health` | 服务状态 |
| 图像代理 | `/api/images/proxy` | SSRF 防护的图像代理 |
| 下载 | `/api/download/image` | 路径遍历防护的下载 |

> ⚠️ 注意：runtime-removed-feature-inventory.md 显示技能/规则/计划模板等已从 active API 移除。上述端点可能部分已不可用。

## 配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEBUG` | `true` | 调试模式 |
| `DEFAULT_IMAGE_SIZE` | `1024x1024` | 默认图片尺寸 |
| `LAMIMAGER_DATA_DIR` | `<project>/data` | 运行时数据目录 |
| `LAMIMAGER_STATIC_DIR` | `<project>/frontend/dist` | 前端静态文件目录 |

## API 供应商配置

两层模型：
1. **Vendor（供应商）**：名称、base_url、API 密钥（AES-256-GCM 加密）
2. **Model（模型）**：挂在供应商下，model_id、类型（LLM/图像生成/联网搜索）、计费方式

| 类型 | API 端点 |
|---|---|
| LLM | OpenAI 兼容 `/v1/chat/completions` |
| 图像生成 | OpenAI 兼容 `/v1/images/generations` |
| 联网搜索 | `https://google.serper.dev` |

## 常见运维操作

| 操作 | 命令 |
|---|---|
| 重置数据库 | `rm data/lamimager.db`（重启自动重建） |
| 清理上传 | `rm -rf data/uploads/*` |
| 导出计费 | `curl /api/billing/export -o billing.csv` |
| 备份数据库 | `cp data/lamimager.db data/lamimager.db.backup` |
| 迁移到新机器 | 复制数据库 + `.encryption_seed` 文件 |

## 安全机制

- **API 密钥**：AES-256-GCM，文件种子派生（`<DATA_DIR>/.encryption_seed`）
- **SSRF 防护**：图像代理验证 scheme + DNS 解析 + Content-Type
- **路径遍历**：下载端点白名单 `^[\w\u4e00-\u9fff.\-]+$` + 路径包含检查
- **XSS**：Markdown 渲染 HTML 转义 + 危险协议过滤

## 项目规则（project_rules.md）

- 开发中严禁使用批量替换功能
- No emoji, Lucide SVG only
- No card stacking, tables + side drawers
- 添加功能前先检查已有路径/服务/组件能否复用
- New endpoint: router → service → schema → api client → store
- 说中文

### 测试规则

| 类型 | 命名 | Mock 允许？ |
|---|---|---|
| 单元测试 | `test_*_unit.py` | ✅ 允许 mock 外部依赖 |
| 集成测试 | `test_*_pipeline.py` | ⚠️ 可 mock 外部 API，不可 mock 内部模块 |
| E2E 测试 | `test_*_e2e.py` | ❌ 严禁任何 mock |

## 关联

- 架构设计 → [[LamImager 架构设计]]
- 项目概览 → [[LamImager 项目概览]]
- 已移除功能 → [[LamImager 已移除功能]]
