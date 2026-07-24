# Agent 意图编配架构

> 设计日期：2026-05-09 | 状态：待审批

## 问题

Agent 模式下，LLM 独自决定「生成几张图、什么内容、是否满足用户需求」。服务端没有任何机制：
- 校验用户请求的图片数量是否被满足
- 将「三视图: 正面, 侧面, 背面」分解为 3 个独立生成项
- 保证 items 级别的参考图传递
- 区分过程图（锚点、草图）和最终图

exe `test 04` 实测：用户要求「正面，侧面，背面」，Agent 实际输出：1 张三视图 sheet + 1 张风格锚点图 + 1 张三视图 sheet，不是 3 张独立视角图。

## 目标

1. 服务端在 Agent 执行前解析用户意图为结构化 `AgentIntent`
2. 确定性任务（三视图、多视角、多角色）绕过 LLM 自由决策，走服务端编排
3. 图片产出区分 `final_images` 和 `intermediate_images`
4. 参考图由服务端注入 tool 层，不依赖 LLM 猜测
5. Agent 从「自由决策者」降级为「受约束的执行器」

## 非目标

- 不替换 `run_agent_loop()` 的 LLM 流式调用机制
- 不改变前端 API 接口
- 不引入新的外部依赖
- 不修改数据库 schema（metadata 字段已有，足够承载新结构）

## 架构

```
handle_agent_generate(data)
  │
  ├─ 1. 保存用户消息
  ├─ 2. parse_agent_intent(data) ──→ AgentIntent
  ├─ 3. route_by_intent(intent)
  │      │
  │      ├── multi_item  → execute_multi_item_intent()
  │      ├── iterative   → execute_iterative_intent()
  │      ├── radiate     → execute_radiate_intent()
  │      ├── single      → run_agent_loop() with intent constraint
  │      └── uncertain   → run_agent_loop()  (fallback, 现有行为)
  │
  ├─ 4. validate_agent_result(intent, result)
  └─ 5. persist(intent, final_images, intermediate_images, steps)
```

### 核心数据类

```python
@dataclass
class AgentItem:
    id: str                     # 如 "front", "side", "back"
    label: str                  # 如 "正面", "侧面", "背面"
    prompt_hint: str            # 如 "front view of the character"
    role: str = "final"         # "final" | "anchor" | "sketch"
    reference_urls: list[str] | None = None


@dataclass
class AgentIntent:
    task_type: str              # "single" | "multi_item" | "iterative" | "radiate"
    expected_count: int         # 用户期望的最终图片数
    strategy: str               # "direct" | "iterative" | "radiate"
    items: list[AgentItem]
    references: list[str]       # 从上下文解析出的参考图 URL
    requires_consistency: bool  # 角色/风格一致性要求
    user_goal: str              # 原始用户文本摘要
```

### 意图解析规则 (parse_agent_intent)

服务端用确定性规则解析，不调用 LLM。规则按优先级排列，先匹配的胜出：

| 优先级 | 识别模式 | task_type | expected_count | items |
|--------|----------|-----------|----------------|-------|
| 1 | "三视图" + "正面/侧面/背面" / "three views" + "front/side/back" | multi_item | 3 | [front, side, back] |
| 2 | "正面,侧面,背面" / "front, side, back" (无 sheet/turnaround) | multi_item | 3 | [front, side, back] |
| 3 | "表情包" / "sticker pack" + 逗号/顿号分隔列表 | multi_item | N | N items |
| 4 | "先...再...最后..." / "first...then..." | iterative | N | chain items |
| 5 | "生成 N 张" / "N 张" / "N images" + 列举明细（非"不同风格"） | multi_item | N | N items |
| 6 | "套图/一组/系列" / "set/series/collection" | radiate | N (extracted) | 套图模式 |
| 7 | "同一提示词" / "不同风格" / "variants" / `data.image_count > 1` | single | data.image_count | 无 (single prompt) |
| 8 | 无特殊模式 | uncertain | data.image_count or 1 | 空 |

#### prompt_hint 映射表

multi_item 解析时，label 中文/英文映射到英文 prompt_hint：

```python
PROMPT_HINT_MAP = {
    "正面": "front view",
    "侧面": "side view",
    "背面": "back view",
    "左": "left side",
    "右": "right side",
    "上": "top view",
    "下": "bottom view",
    "前": "front",
    "后": "back",
    "开心": "happy expression",
    "生气": "angry expression",
    "惊讶": "surprised expression",
    "哭": "crying expression",
    "笑": "laughing expression",
    "害羞": "shy expression",
    "酷": "cool expression",
    "正常": "neutral expression",
}
```

不在表中的 label 直接用原文作为 prompt_hint。

### Prompt 生成器 (_generate_item_prompts)

每个 item 需要一个英文生图 prompt。策略：**批量一次 LLM 调用**，输入全部 items + user_goal + references 描述，输出每个 item 的英文 prompt。

```python
async def _generate_item_prompts(
    items: list[AgentItem],
    intent: AgentIntent,
    llm_provider_id: str,
) -> list[str]:
    """
    调用 LLM 一次，为所有 items 批量生成英文生图 prompt。
    返回与 items 同长的 prompt 列表。
    """
    system_msg = (
        "You are a text-to-image prompt engineer. "
        "For each item below, write ONE concise English prompt optimized for image generation. "
        "Each prompt should be independent and self-contained. "
        "Output JSON array of strings, same length as input."
    )
    user_msg = json.dumps({
        "goal": intent.user_goal,
        "items": [{"label": i.label, "hint": i.prompt_hint} for i in items],
        "style": "..." if intent.requires_consistency else "independent",
    }, ensure_ascii=False)

    response = await llm_client.chat([...], model=..., ...)
    prompts = json.loads(response)
    return prompts
```

LLM 的角色：为每个 item 写一个好的英文生图 prompt（保留创造空间），而不是决定产几张图。

### 多 Item 执行器 (execute_multi_item_intent)

```python
async def execute_multi_item_intent(db, intent, data, ...):
    # 1. 批量生成所有 item 的英文 prompt（一次 LLM 调用）
    prompts = await _generate_item_prompts(intent.items, intent, llm_provider_id)
    
    # 2. 并发生成所有 item 的图片
    async def generate_one(item: AgentItem, prompt: str):
        refs = item.reference_urls or intent.references
        tool = GenerateImageTool()
        result = await tool.execute(
            prompt=prompt, count=1, reference_urls=refs,
            db=db, image_provider_id=..., image_size=...,
        )
        return {
            "item_id": item.id, "label": item.label,
            "url": result.meta["image_urls"][0],
            "cost": ..., "tokens_in": ..., "tokens_out": ...,
        }
    
    # asyncio.gather 并发，items 之间无依赖
    final_images = await asyncio.gather(*[
        generate_one(item, prompt)
        for item, prompt in zip(intent.items, prompts)
    ])
    
    return {"final_images": final_images, ...}
```

### 执行策略

| task_type | 策略 | 说明 |
|-----------|------|------|
| multi_item | concurrent | `asyncio.gather` 并发，items 无依赖 |
| iterative | sequential | 前一个输出作为后一个 reference |
| radiate | radiate | 锚点网格 → PIL 裁剪 → chat_edit 扩展 |
| single | agent loop | 保留现有 `run_agent_loop` 行为 |
| uncertain | agent loop | 回退，保持兼容 |

### 结果校验 (validate_agent_result)

```python
def validate_agent_result(intent: AgentIntent, result: dict) -> bool:
    if intent.task_type == "multi_item":
        expected = intent.expected_count
        actual = len(result.get("final_images", []))
        return actual >= expected
    
    if intent.task_type in ("single", "uncertain"):
        actual = len(result.get("images", []))
        return actual >= intent.expected_count if intent.expected_count > 1 else actual >= 1
    
    return True  # iterative/radiate 由各自执行器内部保证
```

对于 `uncertain` 走 agent loop 后的校验：如果 `expected_count > 1` 但只生成 1 张，追加一次 agent 补充分组重试提示给 LLM。

### 图片产出分离

当前 metadata:

```json
{"image_urls": [...], "prompt": "..."}
```

改为:

```json
{
  "intent": {"task_type": "multi_item", "expected_count": 3, ...},
  "final_images": [
    {"item_id": "front", "label": "正面", "url": "..."},
    {"item_id": "side", "label": "侧面", "url": "..."},
    {"item_id": "back", "label": "背面", "url": "..."}
  ],
  "intermediate_images": [
    {"role": "anchor", "label": "风格锚点", "url": "..."},
    {"role": "sketch", "label": "初稿", "url": "..."}
  ],
  "steps": [...]
}
```

数据库消息 `message_type='image'` 的 metadata 保持兼容，前端逐步迁移。

### 执行策略

对于 `multi_item`:
- **direct**: 每 item 独立调用 `generate_image(count=1)`，相互无依赖
- **iterative**: 前一个 item 的输出作为后一个的 reference（草图→精修→动作）
- **radiate**: 先生成锚点网格图，分割后对每格做 `chat_edit` 扩展

策略由 intent 决定，不由 LLM 临时选择。

### 错误处理

multi_item 路径中，单个 item 生成失败不阻断其他 item：
- 失败的 item 在 `final_images` 中标记 `"status": "failed"` + error message
- 成功的 items 正常返回
- SSE 广播失败事件的 item label
- 最终 output 文本中注明失败项，提示用户可重试

### 参考图传递路径

```python
# 1. handle_agent_generate 中解析
refs_from_context = resolve_context_references(data)

# 2. 注入 intent
intent.references = refs_from_context

# 3. 每个 item 继承
for item in intent.items:
    if not item.reference_urls:
        item.reference_urls = intent.references

# 4. tool 层直接拿到，LLM 不参与
```

## 文件清单（新增/修改）

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/services/agent_intent_service.py` | 新增 | Intent 解析 + 路由 + 多 item 执行 |
| `backend/app/services/generate_service.py` | 修改 | `handle_agent_generate` 接入意图层 |
| `backend/app/services/agent_service.py` | 修改 | system prompt 收紧，增加 intent 注入 |
| `backend/app/tools/generate_image.py` | 不变 | 仅暴露 `count` 含义需在 prompt 中收紧 |
| `backend/app/schemas/session.py` | 不变 | 已有字段够用 |

## 验收标准

1. 用户输入「继续生成三视图，正面，侧面，背面」→ 生成 3 张图：正面、侧面、背面各一张
2. 用户输入「生成一张三视图设定表」→ 生成 1 张排版 sheet（不走 multi_item）
3. 用户输入「表情包：开心，生气，惊讶」→ 生成 3 张独立表情图
4. 用户输入「画 3 张不同风格的猫」→ 生成 3 张图
5. `final_images` 中不包含锚点图、过程图
6. 上下文参考图被传递到 `reference_urls` 而非丢失

## 向后兼容

- `handle_agent_generate` 返回值保持 `{output, steps, cost, tokens_in, tokens_out, cancelled, images}` 不变
- `images` 字段继续保持全部图片 URL（兼容前端现有展示）
- 新增 `intent` 和 `final_images` 以可选项形式返回
- 消息 metadata 增加新字段但不删除旧字段
