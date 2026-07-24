# Agent Phase 2: 打通输入到生成全流程

> 设计日期：2026-05-08 | 状态：已审批

## 目标

Agent 模式下，用户一句话（如"生成一套MC表情包"）→ Agent 自动搜索参考 → 生成计划 → 调用生图 API → 图片存入会话。LLM 全程自主决策。

## 核心原则

1. **工具即薄壳**：每个 Agent Tool 调用现有 Service/Client，不重复造轮子
2. **LLM 决策一切**：调用顺序、参数、是否用参考图，全由 LLM 决定
3. **Service 层是唯一真相源**：后续规划/生图功能升级，Agent Tool 不改

## 新增工具

### generate_image（新建）

```
薄包装 ImageClient，不经过 Router/Handle_generate
输入:  prompt (str, LLM决定)
       count (int, 默认1, LLM决定, 上限4)
       reference_urls (list[str], 可选, 从image_search结果中选取的URL)
内部兜底: size=默认, negative_prompt="", provider=默认image_provider
转换:   reference_urls → fetchImageAsBase64 → ImageClient.chat_edit() 或 generate()
输出:   ToolResult(content="已生成N张", meta={image_urls: [...], count: N})
```

### plan（新建）

```
薄包装 plan_template_service + plan stream API
输入:  action: "list" | "apply" | "create" | "generate"
       template_id (action=apply时) / variables (action=apply时)
       name, description, steps (action=create时)
输出:  各action返回结构化结果
```

| action | 调用 | 返回 |
|--------|------|------|
| `list` | `plan_template_service.list_templates()` | 模板清单（名称、描述、策略、步骤数、变量） |
| `apply` | `plan_template_service.apply_template(id, variables)` | 已填变量的计划步骤列表 |
| `create` | `plan_template_service.create_template(data)` | 新模板 ID |
| `generate` | LLM 系统提示词内置（输出计划文本+建议steps结构） | 计划文本 |

## 搜索重试策略

- 配置：`app_settings {key: "search_retry_count", value: 3}`，前端 Settings 页可改
- 实现：在 `web_search` / `image_search` Tool 内部，每次请求最多重试 retry_count 次，每次换搜索词（追加限定词/切英文）
- 返回：`ToolResult(meta={attempts: N, best_attempt: N})` — 告知 LLM 搜索次数
- LLM 自主判断结果是否可用，不可用则转向 plan 或直接 generate_image

## 搜索结果→生成联动

- `image_search` 返回 `meta.sources[].image_url`
- LLM 判断哪些 URL 适合作为参考，传给 `generate_image(reference_urls=[...])`
- 工具内做 URL→base64 转换，传入 `ImageClient.chat_edit()` 的 reference_images
- LLM 可决定不用任何参考图（reference_urls=[]）

## Session 内结果持久化

`handle_agent_generate` 改造：

```
async for event in run_agent_loop(...):
  收集 events → steps 列表

  if ToolResultEvent(name="generate_image"):
    → add_system_message(type="image", metadata={image_urls})
    即时存入图片消息（用户即刻看到）

结束后:
  → add_system_message(type="agent", metadata={
       steps: [...], images: accumulated_urls, ...
     })
```

## 计费

- `generate_image` 沿用现有 `record_billing(detail.type="image_gen")`
- `plan` 的 LLM 调用走现有 `detail.type="plan"`
- Phase 1 的 `detail.type="tool"` 继续用于搜索

## SSE 事件扩展

| 事件 | 用途 |
|------|------|
| `tool_warning` | 搜索重试耗尽，提示用户 |
| 现有 `tool_call`/`tool_result` | generate_image 和 plan 的调用展示 |

## 阶段划分

| 阶段 | 内容 |
|------|------|
| Phase 1（已完成） | web_search + image_search + AgentLoop 基础设施 |
| **Phase 2（本次）** | **generate_image + plan 工具** — 打通搜索→规划→生图全流程 |
| Phase 3（原 Phase 2） | analyze_image（Vision评估）+ upload_cdn |

## 文件清单

| 文件 | 动作 |
|------|------|
| `tools/generate_image.py` | **新建** |
| `tools/plan.py` | **新建** |
| `tools/web_search.py` | **改** — 内部重试逻辑 |
| `tools/image_search.py` | **改** — 内部重试逻辑 |
| `tools/__init__.py` | **改** — 注册新工具 |
| `agent_service.py` | **改** — 注入 image_provider + 解密 key + WarningEvent |
| `generate_service.py` | **改** — handle_agent_generate 收集 image_urls + 即时存图 |
| `schemas/session.py` | **改** — GenerateRequest 可能新增 search_retry_count |
| 前端 `Settings.vue` | **改** — 搜索重试次数配置 |
