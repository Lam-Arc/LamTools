# LamImager Artist Runtime

> 状态：✅ 有效 | 来源：artist-runtime-knowledge.md, artist-loop-tool-agent-architecture.md
>
> Artist 是 LamImager 的核心——不是单纯的生图接口，而是一个"会话编排层"。

## 一句话模型

```
用户消息
  → handle_artist_generate()     # 保存用户消息、准备图像/lineage 上下文
  → artist_orchestrate()         # 组装 PER/CON、历史消息、视觉输入，调用 LLM
  → ArtistRuntime.handle_turn()  # 解析动作，发 SSE，委托 ExecutionEngine 生图
  → 保存 artist 消息              # metadata 包含 artifacts
  → lineage_service 重建 DAG     # 从消息 metadata 重建谱系
```

## Artist Loop 架构

```
Observe → Think/Plan → Act(tool/agent) → Review → Respond
```

### 分层

| 层 | 职责 |
|---|---|
| Persona Layer | PER/CON/MEM 注入、艺术判断、用户回复 |
| Loop Layer | 持有上下文、控制最大循环、调用 planner/tool executor |
| Tool Layer | ArtistToolCall/ArtistToolResult，每个工具只做一件事 |
| Execution Layer | 图像工具统一通过 ExecutionEngine |
| Agent Delegation | 复杂非图像任务委托 Agent graph |

### 工具

| 工具 | 状态 | 行为 |
|---|---|---|
| `chat` | ✅ | 发布 reply_delta，不产生 artifacts |
| `ask_clarification` | ✅ | phase=waiting_clarification |
| `execute_image_plan` | ✅ | infer_strategy → build_plan_steps → ExecutionEngine |
| `review_artifacts` | ✅ | 轻量 vision review |
| `inspect_lineage` | ✅ | 读取 lineage tree |
| `set_lineage_head` | ✅ | 切换 HEAD（验证 image_url 属于 session） |
| `delegate_agent` | ✅ | 委托 Agent graph，结果回到 Artist loop |
| `start_long_task` | ✅ | 按 series_prompts 顺序执行，发 long_task SSE |

## LLM 输出协议

- 纯聊天：直接输出文本
- 需要图像：输出 JSON `{message, actions[], next_phase}`
- 解析模式：`text` / `auto`（先 JSON 失败降级文本）/ `json`（严格）

## Action 类型

| Action | 用途 |
|---|---|
| `chat_only` | 纯聊天 |
| `ask_clarification` | 反问澄清 |
| `generate_anchor` | 生成主图 |
| `generate_pack` | 生成组图（默认 radiate） |
| `refine_target` | 精修目标图 |
| `replace_image` | 替换目标图 |
| `style_reference` | 按参考风格生成 |
| `self_critique` | 非生成动作 |
| `delegate_to_agent` | 委托 Agent |
| `plan_complex_task` | → start_long_task |

## 策略推导

| 条件 | 策略 |
|---|---|
| 单 action + generate_pack | radiate |
| 单 action + 其他 | single |
| anchor + refine/replace/style | iterative |
| 有 generate_pack | radiate |
| 其他多 action | iterative |

## Radiate 模式

1. ExecutionEngine 只生成一张 grid anchor
2. 多模态 LLM 判断 grid 行列（失败则启发式：1-2→nx1, 3-4→2x2, 5-6→3x2...）
3. PIL 裁切每个 cell
4. base64 → HTTP URL 持久化
5. 每个 cell → artifact_type="pack"，parent/root 指向 anchor

## Lineage DAG

- **事实源**：消息 metadata（不是 ArtistStateStore）
- **重建**：`build_lineage_tree()` 从全部 artist 消息 metadata 重建
- **HEAD**：session metadata `lineage_head_url`
- **分支**：同一 parent 的第一个 child 继承父分支，后续 child 自动 branch-N
- **回滚**：switch HEAD only（git checkout 语义）

## SSE 事件

```
artist_turn_started → artist_reply_delta → artist_action_started 
→ artist_image_ready → artist_turn_done → (legacy) artist_done
```

## Complex Task Loop

独立实验模式（`artist.py ct`），内部 observe → decide → tool → observe 循环：
- `generate_image`：生图（支持 items 批量）
- `delegate_agent`：非图像分析
- `finish`：完成
- `ask_user`：暂停确认

## 关联

- 架构设计 → [[LamImager 架构设计]]
- 心智模型 → [[LamImager 心智模型]]
- E2E 测试 → [[LamImager E2E 测试]]
- 计划演进 → [[LamImager 计划演进链]]
