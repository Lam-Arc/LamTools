# Agent 节点分模型配置

日期: 2026-05-14  
状态: 已识别，未实现  
优先级: 中（省钱需求）

---

## 问题

当前 agent graph 所有 LLM 节点（intent / context / planner / prompt_builder / critic）**共用同一个 `llm_provider_id`**（来自 `default_optimize_provider_id` 设置）。

这意味着不能用便宜模型跑 planner、用 vision 模型跑 critic——要么全用贵的 vision 模型，要么全用便宜的纯文本模型（critic 无法评估图片）。

## 目标

让不同节点可以使用不同 LLM provider，在省钱和功能之间按需分配：

| 节点 | 需要什么 | 推荐模型 |
|------|---------|---------|
| intent | 纯文本推理，轻量 | deepseek-chat / qwen3 |
| planner | 纯文本推理，中等 | deepseek-chat / qwen3 |
| prompt_builder | 纯文本推理，中等 | deepseek-chat / qwen3 |
| context | vision 多模态（描述图片） | gpt-4o-mini / qwen2.5-vl |
| critic | vision 多模态（评估生成图） | gpt-4o-mini / qwen2.5-vl |
| decision | 纯代码逻辑，不需要 LLM | 无 |

预算对比示例：
- 现状: 6 次 LLM 调用 × GPT-5.4 = 贵
- 优化后: 3 次 cheap + 2 次 vision-medium = 总费用降 60-80%

## 实现方案

### 方案 A: 多 setting key（推荐）

在 `app_settings` 新增 setting key，每个节点独立可选：

```
agent_planner_provider_id      → planner + prompt_builder 共用
agent_critic_provider_id       → critic + context 共用（vision）
agent_intent_provider_id       → intent 单独
```

`llm_provider_id` 保留作为 fallback——如果某个节点的专用 provider 没配置，回退到 `llm_provider_id`。

### 方案 B: 单一 provider 覆盖全部

不做改动，用户自己选一个支持 vision 的中等价模型（如 gpt-4o-mini）覆盖全部节点。

## 涉及文件

- `backend/app/services/settings_service.py` — 新增 setting key 读写
- `backend/app/core/agent/nodes/*.py` — 各节点读取自己对应的 provider_id
- `backend/app/core/agent/state.py` — state 可能新增字段
- `frontend/src/views/Settings.vue` — 新增下拉选择
- `frontend/src/types/index.ts` — DefaultModelsConfig 扩展

## 决策

待 P3 排期时确定方案 A vs B。
