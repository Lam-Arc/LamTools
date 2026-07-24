# 图像感知上下文与迭代精修 — 实现计划

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 LLM 能通过多模态上下文"看见"已生成图片，用户可一键进入精修模式用选中图片迭代生图。

**Architecture:** 前端扩展 `context_messages` 携带 `image_urls`，后端在优化/规划阶段构建 multimodal content；前端新增精修模式态（输入区参考图 strip + 精修按钮）；后端 `chat_edit()` 保留编号标注让 LLM 能区分多张参考图。

**Tech Stack:** Python 3.14+ / FastAPI / Pydantic, Vue3 / TypeScript / Pinia

---

## Task 1: 后端 Schema — GenerateRequest 扩展

**Files:** `backend/app/schemas/session.py`

**Steps:**
- [ ] Step 1: 在 `GenerateRequest` 中 `reference_images` 行后新增 `reference_labels` 字段：
  ```python
  reference_labels: list[dict] = []
  ```
- [ ] Step 2: 修改 `context_messages` 的类型注解，将 `list[dict]` 改为保留 `list[dict]`（Pydantic 原生支持嵌套 dict），确保旧请求不含 `image_urls` 照样通过验证

**Verification:**
- [ ] 启动后端 `uvicorn app.main:app --port 8000`，用 curl 发一个不含新字段的 generate 请求，确认 200 OK：
  ```bash
  curl -s -X POST http://localhost:8000/api/sessions/{session_id}/generate \
    -H "Content-Type: application/json" \
    -d '{"prompt":"test","context_messages":[{"role":"user","content":"hello"}],"reference_images":[],"reference_labels":[]}' | python -m json.tool
  ```
- [ ] 含 `image_urls` 的新请求也能正常解析，不报 422

**Commit:** `feat: add reference_labels and image_urls fields to GenerateRequest schema`

---

## Task 2: 前端类型 — GenerateRequest 扩展

**Files:** `frontend/src/types/index.ts`

**Steps:**
- [ ] Step 1: 修改 `GenerateRequest` 接口中 `context_messages` 的类型：
  ```typescript
  context_messages?: { role: string; content: string; image_urls?: string[] }[]
  ```
- [ ] Step 2: 新增 `reference_labels` 字段（可选）：
  ```typescript
  reference_labels?: { index: number; source: string; name: string }[]
  ```

**Verification:**
- [ ] `cd frontend && npx tsc --noEmit` 零错误通过

**Commit:** `feat: extend GenerateRequest types with image_urls and reference_labels`

---

## Task 3: 后端 chat_edit() — 保留编号标注

**Files:** `backend/app/utils/image_client.py`

**Steps:**
- [ ] Step 1: `chat_edit()` 方法签名新增 `reference_labels: list[dict] | None = None` 参数
- [ ] Step 2: 替换 `clean_prompt` 逻辑。删掉 `re.sub(r'\[参考图片:\s*[^\]]+\]\s*\n?', '', prompt)` 这行
- [ ] Step 3: 在 `content_parts` 构建前，注入编号映射文本：
  ```python
  labels = reference_labels or []
  image_label_lines = []
  for i in range(len(images)):
      name = labels[i]["name"] if i < len(labels) else f"图片{i+1}"
      image_label_lines.append(f"  [图{i+1}]: {name}")
  label_hint = ""
  if image_label_lines:
      label_hint = "你收到了以下参考图片，编号与图片顺序一一对应：\n" + "\n".join(image_label_lines) + "\n\n"
  ```
- [ ] Step 4: 修改 text content 从 `clean_prompt` 改为 `label_hint + "请根据参考图片和以下指令生成新图片。直接返回生成的图片，不要描述或解释。\n\n指令: " + prompt`
- [ ] Step 5: 删除 `clean_prompt = re.sub(...)` 和 `if not clean_prompt: clean_prompt = prompt.strip()` 两行

**Verification:**
- [ ] `cd backend && python -c "from app.utils.image_client import ImageClient; print('import OK')"` 无报错
- [ ] 检查日志：生成时 `chat_edit()` 发出的 payload 中 text 内容包含 `[图1]` 编号标注

**Commit:** `feat: preserve numbered image labels in chat_edit multimodal content`

---

## Task 4: 后端 multimodal 上下文 — _build_multimodal_context()

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] Step 1: 在文件末尾新增函数 `_build_multimodal_context(messages: list[dict]) -> list[dict]`：
  ```python
  def _build_multimodal_context(messages: list[dict]) -> list[dict]:
      content_parts: list[dict] = []
      content_parts.append({
          "type": "text",
          "text": "以下是对话上下文中的图片，供你参考以理解当前任务的视觉风格和内容：",
      })
      for msg in messages:
          role = msg.get("role", "user")
          content = msg.get("content", "")
          if role == "user":
              content_parts.append({"type": "text", "text": f"[User]: {content}"})
          elif role == "assistant":
              content_parts.append({"type": "text", "text": f"[Assistant]: {content}"})
          for img_url in msg.get("image_urls", []) or []:
              content_parts.append({
                  "type": "image_url",
                  "image_url": {"url": img_url, "detail": "auto"},
              })
      return content_parts
  ```
- [ ] Step 2: 在 `handle_generate()` 中，`if data.context_messages:` 块内，增加判断：如果任一消息有 `image_urls`，调用 `_build_multimodal_context()` 并将结果存入变量 `context_multimodal_content`（稍后在优化/规划时使用），同时仍保留纯文本 `prompt` 拼接给文生图阶段
- [ ] Step 3: 修改优化阶段（`if data.optimize_directions:`），调用 `optimize_prompt` 时如果 `context_multimodal_content` 非空，将其传入（需检查 `prompt_optimizer.py` 的 `optimize_prompt` 是否支持额外上下文，如果不支持则追加到 prompt 末尾作为文本描述）

**Verification:**
- [ ] `cd backend && python -c "from app.services.generate_service import _build_multimodal_context; print('import OK')"` 无报错
- [ ] 用含 `image_urls` 的 context_messages 发 generate 请求，LLM 优化输出应能引用上下文中的图片视觉特征

**Commit:** `feat: support multimodal image context in generate_service`

---

## Task 5: 前端 — sendGenerate() 携带 image_urls

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] Step 1: 在 `sendGenerate()` 函数中，`contextMessages` 构建逻辑（约 line 878-881）改为：
  ```typescript
  const contextMessages = messages.value.slice(-10).map(m => {
      const entry: { role: string; content: string; image_urls?: string[] } = {
          role: m.role,
          content: m.content,
      }
      if (m.message_type === 'image' && m.metadata?.image_urls) {
          const urls = (m.metadata.image_urls as string[]).filter(url =>
              selectedImages.value.includes(url)
          )
          if (urls.length) {
              entry.image_urls = urls
          }
      }
      return entry
  })
  ```
  注意：`selectedImages` 是跨消息共享的数组，这里需要过滤出属于当前消息的图。
- [ ] Step 2: `store.generate()` 调用处，`reference_labels` 字段构建：
  ```typescript
  const refLabels = attachments.value.map((a, i) => ({
      index: i + 1,
      source: 'upload' as const,
      name: a.name,
  }))
  ```
  如果后续 Task 6 精修模式传递 refine 图，也追加到 refLabels 中。

**Verification:**
- [ ] 生成后勾选上一轮的图片，再发送新 prompt，浏览器 Network 面板查看 /api/sessions/{id}/generate 请求体中 `context_messages` 含 `image_urls` 数组

**Commit:** `feat: include selected image URLs in context_messages on send`

---

## Task 6: 前端 — 图片消息区精修按钮

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] Step 1: 在图片消息的操作按钮区（`image-actions` div，约 line 64），在 `[对比选中]` 按钮后新增精修按钮：
  ```html
  <button class="btn btn-sm" @click="enterRefineMode(msg)" :disabled="!selectedImages.length">
    精修({{ selectedImages.length }})
  </button>
  ```
- [ ] Step 2: 新增本地状态变量 `isRefineMode` (ref(false)) 和 `refineImages` (ref<Array<{url:string, source:string, name:string}>>([]))
- [ ] Step 3: 新增函数 `enterRefineMode(msg)`：
  ```typescript
  function enterRefineMode(msg: Message) {
      isRefineMode.value = true
      refineImages.value = selectedImages.value.map((url, i) => ({
          url,
          source: 'refine' as const,
          name: `第${i+1}张`,
      }))
      selectedImages.value = []
      inputText.value = ''
  }
  ```
- [ ] Step 4: 新增函数 `exitRefineMode()`：
  ```typescript
  function exitRefineMode() {
      isRefineMode.value = false
      refineImages.value = []
  }
  ```
- [ ] Step 5: `sendGenerate()` 开头增加判断：如果 `isRefineMode` 为 true，将 `refineImages` 的 URL 通过 `fetchImageAsBase64` 转为 base64 填入 `reference_images`

**Verification:**
- [ ] 生成一组图后，勾选其中 1-2 张，点击"精修(N)"按钮，确认输入区进入精修模式
- [ ] 退出精修后输入区恢复常态

**Commit:** `feat: add refine button on image messages`

---

## Task 7: 前端 — 精修模式 UI（参考图 strip + 状态切换）

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] Step 1: 在 `input-area` div 顶部增加精修模式标签栏（`v-if="isRefineMode"`）：
  ```html
  <div class="refine-header" v-if="isRefineMode">
      <span class="refine-label">精修模式</span>
      <button class="btn btn-sm" @click="exitRefineMode">退出精修</button>
  </div>
  ```
- [ ] Step 2: 将原有的 `attachment-preview` div 改为条件渲染：精修模式显示参考图 strip，常态显示附件缩略图：
  ```html
  <!-- 精修模式: 参考图 strip -->
  <div class="refine-strip" v-if="isRefineMode && refineImages.length">
      <div v-for="(img, i) in refineImages" :key="i" class="refine-strip-item">
          <img :src="img.url" class="refine-strip-thumb" />
          <span class="refine-strip-label">{{ img.source }} / {{ img.name }}</span>
          <button class="attachment-remove" @click="refineImages.splice(i, 1)">x</button>
      </div>
      <label class="refine-add-btn" title="追加图片">
          <input type="file" accept="image/*" multiple @change="handleFileUpload($event, 'image')" hidden />
          + 追加
      </label>
  </div>
  <!-- 常态: 附件缩略图 -->
  <div class="attachment-preview" v-else-if="attachments.length">
      ...
  </div>
  ```
- [ ] Step 3: 输入框 placeholder 切换：
  ```html
  :placeholder="isRefineMode ? '基于参考图进行修改...' : '输入生图指令...'"
  ```
- [ ] Step 4: 发送按钮文案切换：
  ```html
  {{ (currentSessionId && isSessionBusy(currentSessionId)) ? '任务进行中...' : (isRefineMode ? '精修发送' : '发送') }}
  ```
- [ ] Step 5: `sendGenerate()` 中，精修模式下发送时同时构建 `reference_labels`：
  ```typescript
  const refLabels = refineImages.value.map((img, i) => ({
      index: i + 1,
      source: img.source,
      name: img.name,
  }))
  ```
  并存到 `reference_labels` 字段。同时 `reference_images` 取 refineImages 的 base64 版本。

**Verification:**
- [ ] 精修模式下 UI 要素全部正确显示：标签栏、参考图 strip、placeholder、"精修发送"按钮
- [ ] 点击参考图的 × 可移除单张图
- [ ] 点击"退出精修"恢复常态
- [ ] Network 面板确认精修发送的请求体包含 `reference_labels` 和 `reference_images`

**Commit:** `feat: refine mode UI with reference image strip and mode toggle`

---

## Task 8: 集成验证

**Steps:**
- [ ] Step 1: `cd backend && python -c "from app.main import app; print('app OK')"` 确认导入无错误
- [ ] Step 2: `cd frontend && npx tsc --noEmit` 类型检查通过
- [ ] Step 3: `cd frontend && npm run build` 构建成功
- [ ] Step 4: 启动后端和前端，完整走通以下流程：
  1. 创建会话 → 输入 prompt → 生成 2 张图
  2. 勾选生成的图 → 点击"精修(1)" → 进入精修模式
  3. 输入精修指令 → 点击"精修发送" → 确认生成成功且使用 chat_edit 模式
  4. 勾选图片 → 正常发送（非精修模式）→ 检查 Network 请求中 `context_messages` 含 `image_urls`
  5. 点"退出精修" → 输入区恢复常态
- [ ] Step 5: `git diff --stat` 确认只改了预期文件（6 个文件）

**Commit:** (合并到前面 commit，此处仅验证)

---

## 改动文件汇总

| # | 文件 | 新增 | 修改 |
|---|------|------|------|
| 1 | `backend/app/schemas/session.py` | 1 字段 | 1 字段类型 |
| 2 | `frontend/src/types/index.ts` | 1 字段 | 1 字段类型 |
| 3 | `backend/app/utils/image_client.py` | — | chat_edit() 标注逻辑 |
| 4 | `backend/app/services/generate_service.py` | 1 函数 | handle_generate() 上下文处理 |
| 5 | `frontend/src/views/Sessions.vue` | ~80 行 UI + ~40 行逻辑 | sendGenerate() 构建逻辑 |
