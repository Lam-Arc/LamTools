# LamImager API 参考

基础 URL: `http://localhost:8000/api`

## 认证

无（单用户桌面应用）。

## 通用响应格式

### 成功
```json
{
  "id": "uuid-string",
  "field1": "value1",
  "created_at": "2026-05-06T12:00:00"
}
```

### 错误
```json
{
  "detail": "错误信息"
}
```

---

## 会话

### 列出会话
```
GET /api/sessions
```

响应: `Session[]`

```json
[
  {
    "id": "uuid",
    "title": "新会话",
    "created_at": "2026-05-07T12:00:00",
    "updated_at": "2026-05-07T12:00:00",
    "message_count": 5,
    "cost": 0.15,
    "tokens": 1234
  }
]
```

### 创建会话
```
POST /api/sessions
```

请求体:
```json
{
  "title": "我的会话"
}
```

响应: `Session`

### 获取会话
```
GET /api/sessions/{id}
```

响应: `Session`

### 更新会话
```
PUT /api/sessions/{id}
```

请求体:
```json
{
  "title": "更新后的标题"
}
```

### 删除会话
```
DELETE /api/sessions/{id}
```

### 获取会话消息
```
GET /api/sessions/{id}/messages
```

响应: `Message[]`

```json
[
  {
    "id": "uuid",
    "session_id": "uuid",
    "role": "user",
    "content": "生成一只猫",
    "message_type": "text",
    "metadata": {},
    "created_at": "2026-05-07T12:00:00"
  }
]
```

### 添加消息到会话
```
POST /api/sessions/{id}/messages
```

请求体:
```json
{
  "content": "消息文本",
  "message_type": "text",
  "metadata": {}
}
```

消息类型: `text` | `image` | `optimization` | `plan` | `skill` | `error` | `agent`

规划消息的 metadata:
```json
{
  "type": "plan",
  "steps": [
    {"prompt": "英文提示词用于 API", "negative_prompt": "...", "description": "中文步骤描述"}
  ],
  "description": "原始用户输入"
}
```

响应: `Message`

### 实时任务事件 (SSE)
```
GET /api/sessions/events
```

Content-Type: `text/event-stream`

SSE 事件:
- `data: {"type": "snapshot", "data": {"session_id": {"status": "generating", ...}}}` - 初始状态快照
- `data: {"type": "task_update", "data": {"session_id": "uuid", "status": "generating", "progress": 2, "total": 4, "message": "..."}}` - 任务状态变化
- `data: {"type": "ping", "data": {}}` - 30秒心跳

### 在会话中生成图片
```
POST /api/sessions/{id}/generate
```

请求体:
```json
{
  "prompt": "一只毛茸茸的猫坐在椅子上",
  "negative_prompt": "模糊, 低质量",
  "image_count": 1,
  "image_size": "1024x1024",
  "skill_ids": [],
  "optimize_directions": ["detail_enhancement"],
  "custom_optimize_instruction": "",
  "reference_images": ["data:image/png;base64,..."],
  "reference_labels": [{"index": 1, "source": "upload", "name": "photoA.png"}],
  "context_messages": [{"role": "user", "content": "...", "image_urls": ["http://localhost:8000/api/images/xxx.png"]}],
  "plan_strategy": "parallel",
  "agent_mode": false,
  "agent_tools": ["web_search", "image_search", "generate_image", "plan"],
  "agent_plan_strategy": ""
}
```

> **注意**: `agent_plan_strategy` 已弃用 — 后端现在根据意图解析自动决定策略。该字段仍被接受但会被忽略。

响应: `Message` (包含生成图片的助手消息)

> **图生图**: 当 `reference_images` 非空时，后端使用三级降级:
> 1. `POST /v1/chat/completions` 多模态消息 + 编号标签 (图1, 图2...)
> 2. `POST /v1/images/edits` (原生 OpenAI，部分代理可能不支持)
> 3. Vision LLM 视觉描述 → `POST /v1/images/generations` (纯文字兜底)
>
> **多模态上下文**: `context_messages` 可包含 `image_urls` 用于 LLM 视觉上下文。存在时后端通过 `_build_multimodal_context()` 构建多模态消息。
>
> **Agent 模式**: 当 `agent_mode` 为 `true` 时，端点委托给 `handle_agent_generate`，使用指定的 `agent_tools` 调用 `AgentLoop`。可用工具: `web_search`、`image_search`、`generate_image`、`plan`。LLM 自主决定工具调用顺序。

### 取消 Agent 任务
```
POST /api/sessions/{id}/cancel
```
取消正在进行的 Agent 任务。通过每会话 `asyncio.Event` 实现，Agent 循环在轮次间检查。

响应: `{"message": "Cancelled"}`

### Agent Checkpoint
```
POST /api/sessions/{id}/agent/checkpoint
```
批准、重试或重新规划 Agent 检查点 (如锚点网格质量检查)。Checkpoint 在 300 秒超时后自动拒绝。

请求体:
```json
{
  "action": "approve",
  "feedback": "",
  "retry_level": "approve"
}
```

`action` 值: `"approve"` (继续) | `"retry_step"` (重新执行当前步骤) | `"replan"` (回到规划节点)。其他值均视为拒绝。

`retry_level` 值: `"approve"` | `"retry_step"` | `"replan"` — 如省略，从 `action` 推导。

响应:
```json
{
  "status": "approved",
  "step": "anchor_grid"
}
```

---

## 设置

### 获取默认模型
```
GET /api/settings/default-models
```

响应:
```json
{
  "default_optimize_provider_id": "uuid",
  "default_image_provider_id": "uuid",
  "default_plan_provider_id": "uuid",
  "default_image_width": 1024,
  "default_image_height": 1024,
  "max_concurrent": 5
}
```

### 更新默认模型
```
PUT /api/settings/default-models
```

请求体:
```json
{
  "default_optimize_provider_id": "uuid",
  "default_image_provider_id": "uuid",
  "default_plan_provider_id": "uuid",
  "default_image_width": 1024,
  "default_image_height": 1024,
  "max_concurrent": 5
}
```

### 获取任意设置
```
GET /api/settings/{key}
```

支持的键: `search_retry_count`, `download_directory`

响应:
```json
{
  "key": "download_directory",
  "value": {
    "value": "D:\\Downloads\\images"
  }
}
```

### 设置任意设置
```
PUT /api/settings/{key}
```

请求体:
```json
{
  "value": "D:\\Downloads\\images"
}
```

---

## 供应商/模型

### 列出供应商
```
GET /api/vendors
```

响应: `Vendor[]`

```json
[
  {
    "id": "uuid",
    "name": "OpenAI",
    "base_url": "https://api.openai.com",
    "api_key_masked": "****xxxx",
    "is_active": true,
    "model_count": 3,
    "created_at": "2026-05-10T12:00:00",
    "updated_at": "2026-05-10T12:00:00"
  }
]
```

### 创建供应商
```
POST /api/vendors
```

请求体:
```json
{
  "name": "OpenAI",
  "base_url": "https://api.openai.com",
  "api_key": "sk-xxxxx",
  "is_active": true
}
```

### 获取/更新/删除供应商
```
GET /api/vendors/{id}
PUT /api/vendors/{id}
DELETE /api/vendors/{id}
```

### 测试连接
```
POST /api/vendors/{id}/test
```

### 列出供应商下的模型
```
GET /api/vendors/{id}/models
```

响应: `ApiProvider[]`

### 在供应商下创建模型
```
POST /api/vendors/{id}/models
```

请求体:
```json
{
  "nickname": "GPT-4o",
  "model_id": "gpt-4o",
  "provider_type": "llm",
  "billing_type": "per_token",
  "unit_price": 0.01,
  "currency": "USD"
}
```
注意：`base_url` 和 `api_key` 继承自供应商。

---

## 提供商

### 列出提供商
```
GET /api/providers
```

查询参数:
- `provider_type` (可选): `image_gen` | `llm` | `web_search`

响应: `ApiProvider[]`

### 创建提供商
```
POST /api/providers
```

请求体:
```json
{
  "nickname": "OpenAI GPT-4",
  "base_url": "https://api.openai.com",
  "model_id": "gpt-4o",
  "api_key": "sk-xxxxx",
  "provider_type": "llm",
  "billing_type": "per_token",
  "unit_price": 0.01,
  "currency": "USD",
  "is_active": true
}
```

响应: `ApiProvider` (api_key 显示为 `****xxxx`)

### 获取提供商
```
GET /api/providers/{id}
```

响应: `ApiProvider`

### 更新提供商
```
PUT /api/providers/{id}
```

请求体: 部分 `ApiProviderCreate` (省略 `api_key` 则保留当前值)

响应: `ApiProvider`

### 删除提供商
```
DELETE /api/providers/{id}
```

响应: `{"message": "Provider deleted"}`

### 测试连接
```
POST /api/providers/{id}/test
```

响应:
```json
{
  "success": true,
  "message": "连接成功"
}
```

---

## 技能

### 列出技能
```
GET /api/skills
```

响应: `Skill[]`

### 创建技能
```
POST /api/skills
```

请求体:
```json
{
  "name": "产品摄影",
  "description": "专业产品拍摄风格",
  "prompt_template": "Professional product photo of {subject}, studio lighting, white background, {prompt}",
  "parameters": {"subject": "product"},
  "is_builtin": false
}
```

响应: `Skill`

### 导入技能
```
POST /api/skills/import
```

请求体: 与创建技能相同

响应: `Skill`

### 更新/删除技能
```
PUT /api/skills/{id}
DELETE /api/skills/{id}
```

---

## 规则

### 列出规则
```
GET /api/rules
```

查询参数:
- `rule_type` (可选): `default_params` | `filter` | `workflow`

响应: `Rule[]`

### 创建规则
```
POST /api/rules
```

请求体:
```json
{
  "name": "默认负面提示词",
  "rule_type": "filter",
  "config": {
    "negative_keywords": ["模糊", "低质量", "水印"]
  },
  "is_active": true,
  "priority": 10
}
```

响应: `Rule`

### 切换规则激活状态
```
PUT /api/rules/{id}/toggle
```

响应: `Rule`

---

## 账单

### 获取汇总
```
GET /api/billing/summary
```

响应:
```json
{
  "today": 1.23,
  "month": 45.67,
  "total": 123.45,
  "currency": "CNY"
}
```

### 获取详情
```
GET /api/billing/details
```

查询参数:
- `start_date`: ISO 日期字符串
- `end_date`: ISO 日期字符串
- `provider_id`: UUID
- `session_id`: UUID
- `page`: int (默认 1)
- `page_size`: int (默认 20)

响应:
```json
{
  "total": 100,
  "page": 1,
  "page_size": 20,
  "records": [BillingRecord]
}
```

### 导出 CSV
```
GET /api/billing/export
```

查询参数:
- `start_date`, `end_date`

响应: `text/csv` 附件

### 费用明细
```
GET /api/billing/breakdown
```

响应:
```json
{
  "by_provider": [
    {"provider_id": "uuid", "nickname": "GPT-Image-2", "cost": 5.70, "tokens": 18011}
  ],
  "by_type": [
    {"type": "image_gen", "label": "图像生成", "cost": 5.70, "tokens": 18011, "count": 53},
    {"type": "optimize", "label": "提示词优化", "cost": 0.01, "tokens": 5000, "count": 5},
    {"type": "assistant", "label": "小助手对话", "cost": 0.02, "tokens": 8000, "count": 10},
    {"type": "plan", "label": "规划生成", "cost": 0.01, "tokens": 3000, "count": 2},
    {"type": "vision", "label": "视觉分析", "cost": 0.005, "tokens": 2000, "count": 1}
  ]
}
```

操作类型: `image_gen` | `optimize` | `assistant` | `plan` | `vision` | `agent` | `tool`

---

## 参考图

### 列出参考图
```
GET /api/references
```

查询参数:
- `is_global`: boolean

响应: `ReferenceImage[]`

### 上传参考图
```
POST /api/references/upload
```

Content-Type: `multipart/form-data`

表单字段:
- `file`: File
- `name`: string
- `is_global`: boolean
- `strength`: float (0-1)

响应: `ReferenceImage`

### 更新参考图
```
PUT /api/references/{id}
```

请求体:
```json
{
  "name": "新名称",
  "is_global": true,
  "strength": 0.7,
  "crop_config": {"x": 0, "y": 0, "width": 100, "height": 100}
}
```

---

## 提示词优化

### 优化提示词
```
POST /api/prompt/optimize
```

请求体:
```json
{
  "prompt": "一只猫坐在椅子上",
  "direction": "detail_enhancement",
  "llm_provider_id": "uuid",
  "session_id": "uuid",
  "multimodal_context": null
}
```

方向: `detail_enhancement` | `style_unification` | `composition_optimization` | `color_adjustment` | `lighting_enhancement` | `custom:<instruction>`

多方向可用逗号组合: `detail_enhancement,style_unification`

可选字段 `session_id` 将账单关联到会话。

响应:
```json
{
  "original": "一只猫坐在椅子上",
  "optimized": "一只毛茸茸的三花猫优雅地栖息在复古木椅上，午后柔和的阳光透过蕾丝窗帘洒落，浅景深，暖色调，照片级真实风格",
  "direction": "detail_enhancement"
}
```

### 流式优化提示词
```
POST /api/prompt/optimize/stream
```

Content-Type: `text/event-stream` (SSE)

请求体: 与优化提示词相同。SSE 事件格式与流式 LLM 对话相同 (逐 token)。

### 流式 LLM 对话
```
POST /api/prompt/stream
```

Content-Type: `text/event-stream` (SSE)

请求体:
```json
{
  "messages": [{"role": "user", "content": "你好"}],
  "provider_id": "uuid",
  "session_id": "uuid",
  "temperature": 0.7,
  "stream_type": "assistant",
  "agent_tools": ["web_search", "image_search"]
}
```

`stream_type`: `"assistant"` (默认) 用于通用聊天及计费分类。

`agent_tools` (可选): LLM 可调用的工具列表。支持 `web_search`、`image_search`、`generate_image`、`plan`。启用后响应流中会包含 `tool_call` / `tool_result` 事件。

SSE 事件:
- `data: {"token": "词"}` - 每个生成的 token
- `data: {"done": true, "cost": 0.001}` - 完成事件，包含账单
- `data: {"error": "信息"}` - 错误事件

### 流式规划生成
```
POST /api/prompt/plan
```

Content-Type: `text/event-stream` (SSE)

请求体: 与流式 LLM 对话相同。账单以 `type: "plan"` 记录。

### 图片代理
```
GET /api/images/proxy?url=<encoded_url>
```

服务端图片代理，避免 CORS 问题。前端在迭代精修时获取前一步输出图片时使用。

安全: 仅允许 `http`/`https` URL。DNS 解析阻止私有/回环 IP。响应 Content-Type 必须为 `image/*`。

---

## 规划模板

### 列出模板
```
GET /api/plan-templates
```

响应: `PlanTemplate[]`

```json
[
  {
    "id": "uuid",
    "name": "产品展示",
    "description": "专业产品摄影模板",
    "strategy": "parallel",
    "steps": [{"prompt": "...", "description": "..."}],
    "variables": [{"key": "product", "type": "string", "label": "产品名", "default": ""}],
    "is_builtin": true,
    "created_at": "2026-05-07T12:00:00",
    "updated_at": "2026-05-07T12:00:00"
  }
]
```

### 创建/获取/更新/删除模板
```
POST /api/plan-templates
GET /api/plan-templates/{id}
PUT /api/plan-templates/{id}
DELETE /api/plan-templates/{id}
```

### 应用模板 (变量替换)
```
POST /api/plan-templates/{id}/apply
```

请求体: `{"variables": {"subject": "猫", "background": "花园"}}`

响应: `{"steps": [{"prompt": "猫肖像, 专业灯光, 花园背景", ...}]}`

---

## 仪表盘

### 获取统计
```
GET /api/dashboard/stats
```

响应:
```json
{
  "total_sessions": 10,
  "total_images": 35,
  "total_generations": 7,
  "monthly_cost": 12.34
}
```

---

## 下载

### 下载图片到指定目录
```
POST /api/download/image
```

将图片从 URL 保存到配置的下载目录。需要先通过 `PUT /api/settings/download_directory` 设置 `download_directory`。

安全: 文件名通过白名单正则 `^[\w\u4e00-\u9fff.\-]+$` 验证。解析后的路径必须在下载目录内 (路径遍历防护)。

请求体:
```json
{
  "url": "https://example.com/image.png",
  "filename": "image.png"
}
```

文件已存在时自动追加编号: `image (1).png`, `image (2).png`。

响应:
```json
{
  "success": true,
  "path": "D:\\Downloads\\images\\image.png",
  "size": 123456
}
```

错误:
- `400` — 下载目录未配置或路径不存在
- `502` — 从源 URL 下载失败

---

## 健康检查

```
GET /api/health
```

响应:
```json
{
  "status": "ok",
  "version": "0.4.0-alpha",
  "author": "霖二",
  "license": "MIT"
}
```
