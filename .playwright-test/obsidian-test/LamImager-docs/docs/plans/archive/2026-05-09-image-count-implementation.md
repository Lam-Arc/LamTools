# 图像生成数量机制优化 — 实现计划

> **For agentic workers:** Use executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化 image_count 机制：纯文本生图用 n=N 单次调用、Semaphore 配置化、前端自定义数量、后端校验上限。

**Architecture:** 后端 `generate_service.py` 改动核心逻辑，前端 `Sessions.vue` 加自定义数量组件，`session.py` schema 加校验。

**Tech Stack:** Python 3.14+ / FastAPI / Vue3

---

## Task 1: 后端 schema 加 image_count 校验上限

**Files:** `backend/app/schemas/session.py`

**Steps:**
- [ ] 在文件头部导入 Field：`from pydantic import BaseModel, ConfigDict, Field`
- [ ] 将 line 50 的 `image_count: int = 1` 改为 `image_count: int = Field(1, ge=1, le=16)`

**Verification:**
- [ ] `python -m py_compile backend/app/schemas/session.py` 无报错
- [ ] 发送 `image_count=20` 请求应返回 422 校验错误

**Commit:** `feat(schema): add image_count validation (ge=1, le=16)`

---

## Task 2 + 3: 纯文本 n=N + Semaphore 配置化

**Files:** `backend/app/services/generate_service.py`

这两个改动都在 `generate_images_core` 函数内（line 201-315），合并为一个 Task 避免冲突。

### 改动 A：纯文本分支用 n=image_count 单次调用

替换 line 300-313 的 else 块：

**旧代码（line 300-313）：**
```python
    else:
        async def _generate_one(idx):
            async with semaphore:
                try:
                    r = await client.generate(prompt=prompt, negative_prompt=negative_prompt, n=1, size=image_size)
                    return ImageClient.extract_images(r)
                except Exception as e:
                    logger.error(f"Image generation #{idx} failed: {e}")
                    return []

        tasks = [_generate_one(i) for i in range(image_count)]
        results_list = await asyncio.gather(*tasks)
        for u_list in results_list:
            all_image_urls.extend(u_list)
```

**新代码：**
```python
    else:
        try:
            r = await client.generate(prompt=prompt, negative_prompt=negative_prompt, n=image_count, size=image_size)
            urls = ImageClient.extract_images(r)
            all_image_urls.extend(urls)
        except Exception as e:
            logger.error(f"Pure text generation failed: {e}")
```

### 改动 B：Semaphore 从配置读取

替换 line 221 `semaphore = asyncio.Semaphore(5)`，移到 `if reference_images:` 块内：

**旧代码（line 220-221）：**
```python
    all_image_urls: list[str] = []
    semaphore = asyncio.Semaphore(5)
```

**新代码：**
```python
    all_image_urls: list[str] = []
```

然后在 `if reference_images:` 的下一行（原 line 225）插入：
```python
    if reference_images:
        concurrent_val = await get_setting(db, "max_concurrent")
        max_concurrent = concurrent_val.get("value", 5) if concurrent_val else 5
        semaphore = asyncio.Semaphore(max_concurrent)
```

同时在文件头部加入 import（line 193 附近位置合适）：
```python
from app.services.settings_service import get_setting
```

### 改动 C：计费 call_count 调整

在 `handle_generate` 中（line 147），根据是否有参考图调整 call_count：

**旧代码（line 147）：**
```python
        cost = calc_cost(provider, tokens_in=tokens_in, tokens_out=tokens_out, call_count=data.image_count)
```

**新代码：**
```python
        actual_call_count = data.image_count if data.reference_images else 1
        cost = calc_cost(provider, tokens_in=tokens_in, tokens_out=tokens_out, call_count=actual_call_count)
```

### 改动 D：Vision fallback 中的 semaphore 引用

Vision fallback 分支（line 285-299）在 `if reference_images:` 块内，semaphore 已在前置声明，无需改动。确认 line 288 `async with semaphore:` 和 line 270、241 的引用仍然有效。

**Verification:**
- [ ] `python -m py_compile backend/app/services/generate_service.py` 无报错
- [ ] 纯文本生图 image_count=4：API 日志显示单次请求 `n: 4`
- [ ] img2img 生图：semaphore 从配置读取，并行请求数不超过 max_concurrent
- [ ] 计费：纯文本 call_count=1，img2img call_count=image_count

**Commit:** `perf(generate): use n=image_count for text-only generation, configurable semaphore, correct billing call_count`

---

## Task 3 (原 Task 4): Agent prompt 已由用户自行修改，跳过

---

## Task 4 (原 Task 5): 前端自定义数量输入框

**Files:** `frontend/src/views/Sessions.vue`

### 改动 A：添加自定义数量输入

替换 line 231-237 的数量按钮组：

**旧代码：**
```html
            <span class="option-label">数量:</span>
            <button
              v-for="n in [1, 2, 4, 8]" :key="n"
              class="count-btn"
              :class="{ active: imageCount === n }"
              @click="imageCount = n"
            >{{ n }}</button>
```

**新代码：**
```html
            <span class="option-label">数量:</span>
            <button
              v-for="n in [1, 2, 4, 8]" :key="n"
              class="count-btn"
              :class="{ active: imageCount === n && !customCount }"
              @click="setCount(n)"
            >{{ n }}</button>
            <template v-if="customCount">
              <input
                v-model.number="imageCount"
                type="number"
                class="count-input"
                min="1"
                max="16"
                @blur="clampCount"
                @keyup.enter="clampCount"
                ref="customCountInput"
              />
            </template>
            <button
              v-else
              class="count-btn custom-toggle"
              @click="openCustomCount"
            >+自定义</button>
```

### 改动 B：添加 JS 逻辑

在 `<script setup>` 区域（`imageCount` ref line 562 附近）追加：

```typescript
const customCount = ref(false)
const customCountInput = ref<HTMLInputElement | null>(null)

function setCount(n: number) {
  imageCount.value = n
  customCount.value = false
}

function openCustomCount() {
  customCount.value = true
  nextTick(() => {
    customCountInput.value?.focus()
  })
}

function clampCount() {
  if (imageCount.value < 1) imageCount.value = 1
  if (imageCount.value > 16) imageCount.value = 16
}
```

需要在 `<script setup>` 的 import 中确保已有 `nextTick` 和 `ref`（vue 已有）。

### 改动 C：添加输入框样式

在 `<style scoped>` 区域追加：

```css
.count-input {
  width: 52px;
  height: 26px;
  padding: 0 4px;
  border: 1px solid #d0d0d0;
  border-radius: 4px;
  text-align: center;
  font-size: 13px;
  background: #fff;
  outline: none;
}
.count-input:focus {
  border-color: #000;
}
.count-btn.custom-toggle {
  font-size: 12px;
  padding: 0 6px;
  opacity: 0.7;
}
```

**Verification:**
- [ ] `npm run build` 前端构建通过
- [ ] 点击 `+自定义` → 数字输入框出现，自动聚焦
- [ ] 输入 6 → blur → 值保持 6
- [ ] 输入 20 → blur → clamp 到 16
- [ ] 点击快捷按钮 → 退出自定义模式，imageCount 变为对应值
- [ ] 生成请求 payload 中 `image_count` 为自定义值

**Commit:** `feat(ui): add custom image count input (1-16)`

---

## 执行顺序

所有 Task 修改不同文件，可并行执行：

```
Task 1 (schema) ─┐
Task 2+3 (generate) ─┼─ 全部并行
Task 4 (前端) ───┘
```

---

## 改动文件清单

| 文件 | 改动 |
|------|------|
| `backend/app/schemas/session.py` | line 50: `Field(1, ge=1, le=16)` + import Field |
| `backend/app/services/generate_service.py` | line 221: 移除 hardcoded semaphore；line 225: 插入读取配置+创建semaphore；line 300-313: 替换为单次 n=image_count；line 147: call_count 按有无参考图区分；顶部 import get_setting |
| `frontend/src/views/Sessions.vue` | line 231-237: 添加自定义输入框；script: 添加 customCount/customCountInput ref + 3 个函数；style: 添加 .count-input 和 .custom-toggle 样式 |
