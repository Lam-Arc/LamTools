# 图像生成数量机制优化

> **For agentic workers:** Use executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化 image_count 参数机制：前端支持自定义数量、纯文本生图用 n=N 单次调用替代并行 n=1、Semaphore 配置化、Agent count 解禁、后端校验上限。

**Architecture:** 纯后端 Python 层改动为主，前端仅加一个交互组件。无新依赖。

**Tech Stack:** Python / FastAPI / Vue3

---

## 设计决策

| 决策 | 说明 |
|------|------|
| img2img 保持并行 n=1 | chat_edit/edit 端点对 n>1 支持不稳定，不变 |
| 纯文本生图用 n=image_count | OpenAI 兼容 API 原生支持，减少 HTTP 往返 |
| call_count 语义同步 | n=N 时 call_count=1；并行 n=1 时 call_count=image_count |
| Agent count 解禁 | 允许简单单轮需求用 count>1，复杂多步仍走 plan |
| max_concurrent 已存在 | 数据库和 settings API 已有，仅需在 generate_service 中读取使用 |

---

## Task 1: 后端校验 image_count 上限

**Files:** `backend/app/schemas/session.py`

**Steps:**
- [ ] `GenerateRequest.image_count` 加 `Field` 校验：`image_count: int = Field(1, ge=1, le=16)`

**Verification:**
- [ ] `python -m py_compile backend/app/schemas/session.py`

**Commit:** `feat(schema): add image_count validation (ge=1, le=16)`

---

## Task 2: 纯文本生图用 n=image_count 单次调用

**Files:** `backend/app/services/generate_service.py`

**背景:** `generate_images_core` 中纯文本分支（line 300-313）当前用 `for i in range(image_count)` + `n=1` 的并行模式，改为单次 `n=image_count` 调用。img2img 分支不动。

**Steps:**
- [ ] 纯文本分支（`else:` 块，line 300-313）改写：
  ```python
  else:
      try:
          r = await client.generate(prompt=prompt, negative_prompt=negative_prompt, n=image_count, size=image_size)
          urls = ImageClient.extract_images(r)
          all_image_urls.extend(urls)
      except Exception as e:
          logger.error(f"Pure text generation failed: {e}")
  ```
- [ ] 移除该分支的 semaphore、asyncio.gather、_generate_one 闭包
- [ ] 调整 `handle_generate` (line 147) 计费：纯文本时 `call_count=1`（因为一次调用 n=N）。由于 `handle_generate` 不知道是否走 img2img 路径，改为在 `generate_images_core` 返回额外字段 `call_count` 或直接让 `handle_generate` 用 `1`（简化：纯文本占大多数场景，直接改 line 147 为 `call_count=1`）

**注意:** `handle_generate` line 128 的 `total=data.image_count` 进度提示保留不变（语义正确：要生成 N 张图）。

**Verification:**
- [ ] `python -m py_compile backend/app/services/generate_service.py`
- [ ] 纯文本生图 n=4 时，API 日志显示单次请求 `n: 4`

**Commit:** `perf(generate): use n=image_count for text-only generation instead of parallel n=1`

---

## Task 3: Semaphore 从配置读取

**Files:** `backend/app/services/generate_service.py`

**背景:** `generate_images_core` line 221 `semaphore = asyncio.Semaphore(5)` 硬编码，改为从 `app_settings` 读取 `max_concurrent`。img2img 分支仍用 semaphore 控制并行。

**Steps:**
- [ ] 在 `generate_images_core` 开头读取 `max_concurrent` 设置：
  ```python
  from app.services.settings_service import get_setting
  concurrent_val = await get_setting(db, "max_concurrent")
  max_concurrent = concurrent_val.get("value", 5) if concurrent_val else 5
  semaphore = asyncio.Semaphore(max_concurrent)
  ```
- [ ] 移除原来的 `semaphore = asyncio.Semaphore(5)`（line 221），移到 reference_images 分支内部（因为纯文本分支已不需要 semaphore）

**Verification:**
- [ ] `python -m py_compile backend/app/services/generate_service.py`
- [ ] 修改 settings 中 max_concurrent=3，img2img 生图时最多3个并行请求

**Commit:** `feat(generate): read semaphore limit from app_settings max_concurrent`

---

## Task 4: Agent count>1 解禁

**Files:** `backend/app/services/agent_service.py`

**背景:** 系统提示词 line 103-104 写死 `严禁使用 generate_image(count>1)`，与工具定义矛盾。改为允许简单单轮需求使用 count>1。

**Steps:**
- [ ] 修改 `AGENT_SYSTEM_PROMPT` 中相关段落：
  ```
  旧: 1. 单张图 → 直接 generate_image(prompt, count=1)
       严禁使用 generate_image(count>1)
  新: 1. 简单多图需求 → 直接 generate_image(prompt, count=N)，如画4张不同颜色的猫
     2. 需要不同风格/构图的复杂多图 → 调用 plan 工具使用模板
  ```
- [ ] 调整后续编号

**Verification:**
- [ ] `python -m py_compile backend/app/services/agent_service.py`
- [ ] Agent 模式输入「画3只不同颜色的猫」应直接调用 generate_image(count=3)

**Commit:** `feat(agent): allow generate_image count>1 for simple multi-image requests`

---

## Task 5: 前端自定义数量输入框

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 在 `[1, 2, 4, 8]` 按钮组后添加 `+自定义` 按钮
- [ ] 点击后切换为 `<input type="number" min="1" max="16" v-model.number="imageCount">`
- [ ] 失焦或回车后若值超出 1-16 则 clamp；再次点击按钮恢复快捷模式
- [ ] 快捷按钮点击时退出自定义模式

**Verification:**
- [ ] `npm run build` (前端构建通过)
- [ ] 自定义数量 6，发送请求 payload 中 `image_count: 6`
- [ ] 输入 20 自动 clamp 到 16

**Commit:** `feat(ui): add custom image count input (1-16)`

---

## 执行顺序

```
Task 1 (校验上限)    ─┐
Task 2 (n=N 调用)    ─┤ 可并行（不同文件）
Task 3 (Semaphore)  ─┤ 可并行
Task 4 (Agent)      ─┤ 可并行
Task 5 (前端)       ─┘ 可并行
```

所有 Task 修改不重叠，可全部并行执行。

---

## 改动文件清单

| 文件 | Task | 改动类型 |
|------|------|----------|
| `backend/app/schemas/session.py` | Task 1 | 加 Field 校验 |
| `backend/app/services/generate_service.py` | Task 2, 3 | 纯文本分支改写 + 读取配置 |
| `backend/app/services/agent_service.py` | Task 4 | 修改提示词 |
| `frontend/src/views/Sessions.vue` | Task 5 | 加自定义输入组件 |
