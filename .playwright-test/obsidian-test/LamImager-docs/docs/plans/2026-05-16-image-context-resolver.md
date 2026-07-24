# ImageContextResolver 实现计划

> **For agentic workers:** Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现意图驱动的候选图片选择器，解决 agent mode 下修改/精修请求不自动携带上一张图作为 reference 的问题。

**Architecture:** 在 `handle_agent_generate()` 入口前插入 `ImageContextResolver`，根据用户 prompt 的修改意图强度和会话中的图片历史，决定哪些图片作为 `reference_images`（image edit 输入）、哪些作为 `context_images`（LLM 理解用）、是否需要澄清。不改变 intent 分类逻辑，不改变 LangGraph 图结构。

**Tech Stack:** Python 3.14+ / regex + keyword matching / SQLAlchemy async

## 核心设计

### ImageContextResolution 数据结构

```python
@dataclass
class ImageContextResolution:
    mode: Literal["new_generation", "edit_target", "batch_edit", "style_reference", "ask_clarification"]
    target_images: list[str]       # 要被修改的图 URL（将转为 base64 进 reference_images）
    reference_images: list[str]    # 风格/构图参考图 URL
    context_images: list[str]      # LLM 上下文图 URL（不进 reference_images）
    reason: str                    # 决策理由
    confidence: float              # 0.0-1.0
    clarification: str             # mode=ask_clarification 时的提问文本
```

### 意图检测关键词

```python
MODIFY_INTENT_KEYWORDS = [
    "改", "修", "调", "换", "变", "去", "加", "减", "删",
    "线稿化", "素描化", "卡通化", "油画化", "水彩化",
    "优化", "精修", "继续", "沿着", "就这个方向",
    "再", "更", "稍微", "一点",
    "背景", "脸", "手", "颜色", "配色", "构图", "姿势",
    "modify", "change", "adjust", "fix", "remove", "add",
    "refine", "improve", "continue", "optimize",
]

GROUP_INTENT_KEYWORDS = ["这组", "这几张", "整套", "整套都", "这套", "全部都", "都"]

STYLE_REF_INTENT_KEYWORDS = ["照这个风格", "参考.*氛围", "用.*配色", "构图像", "风格像"]

NEW_GEN_INTENT_KEYWORDS = ["再画", "来个新", "换个完全不同", "生成一张", "新方案", "重新画"]
```

### 决策优先级

```
1. 用户手动选择（refine_mode 图 / UI selected image）
2. 用户文本明确图号："图2"、"第二张"
3. 用户文本明确组："这组"、"整套"
4. 模糊修改意图 → 最近一张可编辑图
5. 无修改意图 → 不自动传上一张
```

### 四个闸门

1. **Intent Gate**: 只有检测到修改/参考意图才自动提升图片
2. **Target Count Gate**: single edit max 1, batch edit max 4, style reference max 2
3. **Ambiguity Gate**: 多张候选且用户没说明 → 返回 clarification
4. **Role Separation Gate**: target → reference_images, style_ref → reference_images, context → 不进 reference_images

---

## Task 1: 创建 ImageContextResolver 服务

**Files:**
- `backend/app/services/image_context_resolver.py` (新建)

**Steps:**
- [ ] Step 1: 创建文件，定义 `ImageContextResolution` dataclass
- [ ] Step 2: 实现意图检测函数 `detect_image_intent(prompt: str) -> ImageIntentType`，使用关键词匹配 + regex，返回 `edit_target / batch_edit / style_reference / new_generation / ambiguous`
- [ ] Step 3: 实现图号解析函数 `resolve_explicit_image_refs(prompt: str, session_images: list[SessionImage]) -> list[SessionImage]`，匹配 "图N"、"第N张"、"第二张" 等模式
- [ ] Step 4: 实现核心函数 `resolve_image_context(prompt, session_images, manual_refine_images, selected_image_id, pinned_images) -> ImageContextResolution`，按优先级决策
- [ ] Step 5: 实现 Ambiguity Gate：当上一条 assistant 消息有多张图且用户只说"改一下"时返回 `ask_clarification`
- [ ] Step 6: 实现 Target Count Gate：single edit max 1, batch max 4, style_ref max 2

**Verification:**
- [ ] 文件存在且无语法错误：`py -3.14 -c "from app.services.image_context_resolver import ImageContextResolver, ImageContextResolution"`

**Commit:** `feat: add ImageContextResolver service with intent-driven image selection`

---

## Task 2: 在 GenerateRequest schema 中添加 refine_mode 信号

**Files:**
- `backend/app/schemas/session.py`

**Steps:**
- [ ] Step 1: 在 `GenerateRequest` 类中添加 `refine_mode: bool = False` 字段
- [ ] Step 2: 添加 `selected_image_url: str = ""` 字段（前端选中的图片 URL）

**Verification:**
- [ ] `py -3.14 -c "from app.schemas.session import GenerateRequest; r = GenerateRequest(prompt='test', refine_mode=True, selected_image_url='http://x'); print(r.refine_mode, r.selected_image_url)"`

**Commit:** `feat: add refine_mode and selected_image_url to GenerateRequest`

---

## Task 3: 集成 ImageContextResolver 到 handle_agent_generate

**Files:**
- `backend/app/services/generate_service.py`

**Steps:**
- [ ] Step 1: 在 `handle_agent_generate()` 中，在 `resolve_context_references()` 调用之前，查询会话中最近的 assistant 图片消息，构建 `session_images` 列表
- [ ] Step 2: 调用 `ImageContextResolver.resolve_image_context()` 获取 `ImageContextResolution`
- [ ] Step 3: 根据 resolution.mode 处理：
  - `edit_target` / `batch_edit`: 将 `target_images` URL 转为 base64，**合并到** `data.reference_images`，并生成对应 `reference_labels`
  - `style_reference`: 将 `reference_images` URL 转为 base64，合并到 `data.reference_images`
  - `ask_clarification`: 通过 SSE 发送 clarification 消息，提前返回（不执行生成）
  - `new_generation`: 不修改 `data.reference_images`
- [ ] Step 4: `context_images` 保持原逻辑（只给 LLM 用），不受 resolver 影响
- [ ] Step 5: 添加日志记录 resolver 的决策结果

**Verification:**
- [ ] 启动服务器，用类似 session 231 的 prompt "画面太杂乱了 改一下" 发送 agent_mode 请求，检查日志中 resolver 的决策和 reference_images 是否非空

**Commit:** `feat: integrate ImageContextResolver into agent generate flow`

---

## Task 4: 前端发送 refine_mode 和 selected_image_url

**Files:**
- `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] Step 1: 在 `sendGenerate()` 构建 `generateData` 时，如果 `isRefineMode.value` 为 true，设置 `generateData.refine_mode = true`
- [ ] Step 2: 如果有选中的精修图（refineImages），将第一张的 URL 设为 `generateData.selected_image_url`
- [ ] Step 3: 删除死代码 `ctxUrls`（line 962-964）

**Verification:**
- [ ] 前端构建无错误：`npm run build`

**Commit:** `feat: send refine_mode and selected_image_url from frontend`

---

## Task 5: 集成到非 agent mode 的 handle_generate

**Files:**
- `backend/app/services/generate_service.py`

**Steps:**
- [ ] Step 1: 在 `handle_generate()` 中也调用 `ImageContextResolver`，当 `data.refine_mode` 为 true 或检测到修改意图时，自动将 target_images 转为 base64 合并到 `data.reference_images`
- [ ] Step 2: 确保非 agent mode 的 `generate_images_core()` 调用能收到正确的 reference_images

**Verification:**
- [ ] 非 agent mode 下发送 "线稿化" 请求，检查是否自动携带上一张图

**Commit:** `feat: integrate ImageContextResolver into non-agent generate flow`

---

## Task 6: 端到端验证

**Files:** 无新文件

**Steps:**
- [ ] Step 1: 启动服务器，创建新会话
- [ ] Step 2: 发送 "江南徽派风格建筑的中国漆画"（agent_mode），确认生成图片
- [ ] Step 3: 发送 "画面太杂乱了 改一下"（agent_mode），检查请求中 reference_images 是否包含上一张图
- [ ] Step 4: 发送 "这张不错，线稿化"（agent_mode），同上验证
- [ ] Step 5: 发送 "再画一只猫"（agent_mode），确认 reference_images 为空（不自动传上一张）
- [ ] Step 6: 检查日志中 ImageContextResolver 的决策记录

**Verification:**
- [ ] 上述 6 步全部通过

**Commit:** 无（验证任务）
