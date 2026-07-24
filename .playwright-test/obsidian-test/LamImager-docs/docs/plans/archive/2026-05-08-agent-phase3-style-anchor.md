# Agent Phase 3: style_anchor 套图策略

> 设计日期：2026-05-08 | 状态：已审批

## 目标

新增 `style_anchor` 生图策略——Agent 检测到「套图」（多子项需求）时，先生成风格锚点网格图，再基于切分的单格参考逐项生成，防止多张图风格跑偏。

## 核心原则

1. **与 plan 体系并列**：`style_anchor` 是 parallel/sequential/iterative 之外的新策略
2. **代码层切分**：PIL 均等切分网格图，LLM 无感知
3. **模板驱动**：内置模板「套图生成」，LLM 只需 `plan(action="apply")`

## 3 级体系

| 级别 | 触发条件 | 产出 | 用途 |
|------|----------|------|------|
| Level 2 | 子项 > 16 | 1 张总体风格参考图 | 锚定宏观方向，作为所有 L1 的 reference |
| Level 1 | 所有套图 | ceil(n/16) 张网格图，每张 ≤4x4 | 锚定子项风格，PIL 切分成单格 reference |
| Level 0 | 每个子项 | N 张独立图 | 基于对应格子的切分图逐项生成 |

子项 ≤ 16：Level 2 跳过，直接 Level 1。

## grid_config 参数

`generate_image` 新增：
```python
grid_config: {"cols": int, "rows": int}  # None=普通生图
```

grid_config 非 None 时：生成网格图 → PIL 按比例切分 → 返回原图 URL + 格子 b64 数组。

参考图走 reference_images（b64），非磁盘文件。

## 内置模板

模板名「套图生成」，策略 `style_anchor`，变量：`items`(list)、`style`(str)、`overall_theme`(str)。

步骤：
- Step0 (L1): anchor 网格图，`grid_config` 自动计算行列（max 4×4）
- Step1..N (L0): expand 逐项生图，`reference_grid_cell` 按格子索引关联切分图

## 模板引擎展开

`handle_agent_generate` 识别 `strategy="style_anchor"` → 按 items 数量和 grid_config 规则展开 Level 2/1/0 步骤 → 逐级执行，上级产出自动作为下级 reference_images 注入。

## L1 用户确认

`checkpoint.enabled: true`（模板控制，非强制）。L1 完成后暂停 → 前端展示锚点图 → 用户确认/提反馈 → 继续或重新生成锚点图。

## 文件清单

| 文件 | 动作 |
|------|------|
| `tools/generate_image.py` | 改 — grid_config + PIL 切分 |
| `services/plan_template_service.py` | 改 — 新增内置模板 |
| `services/generate_service.py` | 改 — style_anchor 展开执行 |
| `agent_service.py` | 改 — checkpoint 挂起/恢复 |
| `routers/session.py` | 改 — checkpoint feedback |
| `frontend/views/Sessions.vue` | 改 — 锚点图展示 + 确认按钮 |
