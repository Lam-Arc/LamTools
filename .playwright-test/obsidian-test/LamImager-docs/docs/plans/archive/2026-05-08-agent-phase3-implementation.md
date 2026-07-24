# Agent Phase 3: style_anchor 套图策略 — 实施计划

> **For agentic workers:** Use executing-plans to implement this plan task-by-task.

**Goal:** `generate_image` 新增 grid_config 网格切分 + 内置「套图生成」模板 + handle_agent_generate 执行 style_anchor 策略。

**Architecture:** PIL 均等切分网格图，模板引擎按 items 数量展开 Level 2/1/0 步骤，checkpoint 暂停等待用户确认锚点图。

**Tech Stack:** Python 3.14+ / PIL / aiohttp / SQLAlchemy / Vue3

---

## Task 1: grid_config 参数 + PIL 切分

**Files:** `backend/app/tools/generate_image.py` (修改)

**Steps:**
- [ ] `parameters.properties` 新增 `grid_config`: `{"type":"object","properties":{"cols":{"type":"integer"},"rows":{"type":"integer"}}}`（可选）
- [ ] `execute()` 签名新增 `grid_config: dict | None = None`
- [ ] 新增 `_generate_grid(prompt, client, grid_config, **kwargs) -> dict` 函数：
  - 调 `client.generate(prompt, n=1)` 生成网格图
  - PIL `Image.open(io.BytesIO(b64_data))` 加载
  - 按 `cols × rows` 计算格子尺寸 → `img.crop(box)` 逐格切
  - 每格 `base64.b64encode(buf)` 返回 b64 数组
  - 返回 `{"image_urls": [原图], "grid_images": [b64_1, b64_2, ...], "grid_config": grid_config}`
- [ ] `execute()` 开头检查 `grid_config`：非 None → 走 `_generate_grid` 路径，跳过原有 count 并行逻辑

**Verification:**
- [ ] `cd backend && python -c "from app.tools.generate_image import GenerateImageTool; p = GenerateImageTool().parameters; print('grid_config' in p['properties'])"` 输出 `True`

**Commit:** `feat: add grid_config parameter and PIL cropping to generate_image`

---

## Task 2: 新增「套图生成」内置模板

**Files:** `backend/app/services/plan_template_service.py` (修改)

**Steps:**
- [ ] `_BUILTIN_TEMPLATES` 列表新增第 5 个模板：
  ```python
  {
      "name": "套图生成",
      "description": "生成风格统一的多子项套图。先生成风格锚点网格图再逐项生成，防跑偏。",
      "strategy": "style_anchor",
      "is_builtin": True,
      "variables": [
          {"key": "items", "type": "array", "label": "子项列表", "default": [], "required": True},
          {"key": "style", "type": "string", "label": "整体风格", "default": "", "required": True},
          {"key": "overall_theme", "type": "string", "label": "主题描述", "default": ""},
      ],
      "steps": [
          {"role": "anchor", "description": "风格锚点网格图", "prompt": "A grid layout showing all items in a unified {style} style...", "grid_config": {"auto": True, "max_cols": 4, "max_cells": 16}},
          {"role": "expand", "description": "逐项生图", "prompt": "{item.prompt}. {style} style.", "grid_config": None, "repeat": "items", "reference_step_indices": [0]},
      ],
  }
  ```

**Verification:**
- [ ] `cd backend && python -c "from app.services.plan_template_service import seed_builtin_templates; print('OK')"`
- [ ] 检查数据库 `SELECT name FROM plan_templates WHERE strategy='style_anchor'` → 返回「套图生成」

**Commit:** `feat: add style_anchor built-in template`

---

## Task 3: handle_agent_generate 执行 style_anchor

**Files:** `backend/app/services/generate_service.py` (修改)

**Steps:**
- [ ] 在 `handle_agent_generate` 事件循环中，检测 `plan` tool 返回 `strategy="style_anchor"`：
  - 从 `item.meta` 取出 `steps`（模板引擎展开后的完整步骤列表）
  - 不再让 LLM 循环决策，直接按步骤顺序执行：
    - anchor 步骤：调 `generate_image(prompt, grid_config=...)` → 拿到 `grid_images[]`
    - expand 步骤：`for item in items` → `generate_image(prompt=item.prompt, reference_urls=[grid_images[i]])`
    - 完成后汇总所有 image_urls → store message
- [ ] `_compute_grid_config(n_items)` 辅助函数：
  - `n <= 4`: cols=2, rows=ceil(n/2)
  - `4 < n <= 9`: cols=3, rows=ceil(n/3)
  - `n > 9`: cols=4, rows=ceil(n/4)

**Verification:**
- [ ] `cd backend && python -c "from app.services.generate_service import _compute_grid_config; print(_compute_grid_config(4), _compute_grid_config(7), _compute_grid_config(12))"`

**Commit:** `feat: execute style_anchor strategy in handle_agent_generate`

---

## Task 4: checkpoint 挂起/恢复

**Files:** `backend/app/services/agent_service.py`, `backend/app/routers/session.py` (修改)

**Steps:**
- [ ] `agent_service.py`: `run_agent_loop` 中 anchor 步骤执行后，若标记 `checkpoint_enabled=True`：
  - yield `CheckpointEvent(image_url, message)` — 新增事件类型
  - 挂起等待：`await _wait_for_checkpoint(session_id)` → 阻塞直到 `/checkpoint` 端点收到请求
- [ ] `agent_service.py`: 新增 `_checkpoint_states: dict[str, asyncio.Event]` 模块级字典，key=session_id
- [ ] `routers/session.py`: `/agent/checkpoint` 端点更新：接收 `{approved: bool, feedback: str}`，set 对应 session 的 event，`feedback` 存入 agent_context 供 redo 使用

**Verification:**
- [ ] 后端运行中，curl `POST /sessions/{id}/agent/checkpoint -d '{"approved":true}'` 返回 `{"status":"resumed"}`

**Commit:** `feat: implement agent checkpoint pause/resume`

---

## Task 5: 前端锚点图展示 + 确认按钮

**Files:** `frontend/src/views/Sessions.vue` (修改)

**Steps:**
- [ ] Agent 执行卡片中，`step.role === "anchor"` 且有 `image_url` 时：展示锚点图预览（`<img>` 标签，max-height 200px）
- [ ] 下方两个按钮：「确认」→ `POST /sessions/{id}/agent/checkpoint {approved:true}`；「不满意」→ 显示 feedback 输入框 → 提交 `{approved:false, feedback:"..."}`
- [ ] 按钮仅在 `event.type === "checkpoint"` 时显示，确认后消失

**Verification:**
- [ ] `cd frontend && npx tsc --noEmit` 无错误

**Commit:** `feat: add anchor image preview and confirm/cancel buttons`

---

## Task 6: 后端验证

**Steps:**
- [ ] `cd backend && python -c "from app.main import app; print('OK')"`
- [ ] 创建 session → POST generate with agent_mode + 套图 prompt → 检查输出含 grid_images

**Commit:** 无

---

## 实施顺序

```
Task 1 (grid_config) → Task 2 (template) → Task 3 (style_anchor exec) → Task 4 (checkpoint) → Task 5 (frontend) → Task 6 (verify)
```
