# LamImager 架构设计

> 状态：⚠️ 可能过时 | 来源：architecture.md, AGENTS.md, artist-runtime-knowledge.md
> 
> ⚠️ AGENTS.md 明确标注：architecture.md / api-reference.md / runbook.md 可能滞后于代码，使用前需对照源码验证。

## 系统总览

```
Browser (Vue3 SPA)
  ↕ HTTP/REST
FastAPI Backend
  Routers → Services → Models
  ↕
SQLite Database
```

## 后端分层

| 层 | 职责 | 关键文件 |
|---|---|---|
| Routers | HTTP 端点 | `app/routers/*.py` (11 模块) |
| Services | 业务逻辑 | `app/services/*.py` |
| Core | Agent 图 + Artist Runtime | `app/core/agent/`, `app/core/artist/` |
| Models | ORM | `app/models/*.py` (10 表) |
| Schemas | Pydantic | `app/schemas/*.py` |
| Utils | 加密/LLM/图像客户端 | `app/utils/*.py` |

## 数据模型

| 表 | 用途 |
|---|---|
| `api_vendors` | API 供应商（名称、地址、加密密钥） |
| `api_providers` | 供应商下的模型（model_id, type, billing, price） |
| `sessions` | 对话会话 |
| `messages` | 会话消息（user/assistant/system/artist） |
| `skills` | 可复用提示词模板 |
| `rules` | 全局规则（默认参数/过滤器/工作流） |
| `billing_records` | 计费记录 |
| `reference_images` | 参考图元数据 |
| `app_settings` | 应用设置 |
| `plan_templates` | 计划模板 |

## 核心调用链

### Artist 生成流程

```
用户消息
  → handle_artist_generate()     # 保存用户消息、准备图像/lineage 上下文
  → artist_orchestrate()         # 组装 PER/CON、历史消息、视觉输入
  → ArtistRuntime.handle_turn()  # LLM 输出 → 解析 → tool 执行 → SSE → 状态更新
  → 保存 artist 消息              # metadata 包含 artifacts
  → lineage_service 重建 DAG     # 从消息 metadata 重建谱系
```

### Artist Runtime 内部

```
handle_turn()
  → 取 session state
  → 发布 artist_turn_started
  → LLM 调用（获取 message + actions JSON）
  → parse_artist_turn()
  → action_to_tool_calls()       # ArtistAction → ArtistToolCall
  → ArtistToolExecutor 执行
    → chat / ask_clarification / execute_image_plan / review_artifacts
    → execute_image_plan → ExecutionEngine
  → 更新 state
  → 发布 artist_turn_done
```

## 安全机制

- **API 密钥**：AES-256-GCM，文件种子派生密钥
- **SSRF 防护**：图像代理验证 scheme + DNS + Content-Type
- **路径遍历**：下载端点白名单 + 路径包含检查
- **XSS**：Markdown 渲染 HTML 转义 + 危险协议过滤

## 关联

- 项目概览 → [[LamImager 项目概览]]
- Artist Runtime 细节 → [[LamImager Artist Runtime]]
- 认知模型 → [[LamImager 心智模型]]
- 已移除功能 → [[LamImager 已移除功能]]
