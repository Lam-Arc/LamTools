# Sessions.vue 拆分实施计划

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Sessions.vue (4082 行) 拆分为 12 个独立子组件，目标压缩至 ~1900 行 (-53%)，每阶段可独立验证。

**Architecture:** 5 阶段渐进拆分。Phase 1 拆无状态叶节点 (零风险)，Phase 2 拆输入区，Phase 3 拆消息卡片，Phase 4 拆 AssistantSidebar (最大块)，Phase 5 收尾清理。所有组件通过 props/emits 通信，不引入 provide/inject。

**Tech Stack:** Vue3 SFC + Pinia + TypeScript

---

## 模块依赖约束

以下 import 规则必须在整个拆分过程中遵守，违反会导致循环引用或编译失败：

| 规则 | 约束 |
|------|------|
| R1 | 子组件 **禁止** import `Sessions.vue` 或 `useSessionStore` |
| R2 | 子组件 **禁止** 直接调用 `sessionApi.*` / `promptApi.*` / `skillApi.*` / `planTemplateApi.*` — 全部通过 emit 委托给父组件 |
| R3 | 子组件可以 import `useProviderStore` / `useBillingStore` (只读 store，不产生循环) |
| R4 | `AssistantSidebar.vue` 内部允许调用 `promptApi.stream*` / `planTemplateApi.*` (这些 API 不依赖 Session store) |
| R5 | 所有子组件放在 `frontend/src/components/session/` 下，与已有 `AgentStreamCard.vue` / `CheckpointOverlay.vue` 同级 |

---

## 共享类型 (新建)

所有拆分子组件复用统一的类型定义，避免交叉引用。

```typescript
// frontend/src/types/index.ts 新增以下类型 (追加到文件末尾)

export interface ContextImage {
  url: string
  source: 'upload' | 'context' | 'refine'
  name: string
  preview?: string
}

export interface Attachment {
  name: string
  type: string
  size: number
  preview?: string
  content?: string
}

export interface DialogToolCall {
  id: string
  name: string
  args: Record<string, unknown>
  content: string
  collapsed: boolean
}

export interface DialogMessage {
  id: number
  role: string
  content: string
  attachments?: Attachment[]
}
```

**验证:** `npm run build` 通过，确认无 `ContextImage` / `Attachment` 类型重复定义。

**Commit:** `types(ui): add ContextImage, Attachment, DialogToolCall, DialogMessage shared types`

---

## Phase 1: 纯展示叶节点 (零风险，4 个 Task)

四个组件均为纯展示 (无本地状态、无 API 调用)，从 Sessions.vue 模板中直接剪切粘贴。

### Task 1.1: Lightbox

**Files:**
- `frontend/src/components/session/Lightbox.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 212-223 剪切 `<div class="lightbox-overlay">...</div>` 整段
- [ ] 创建 `Lightbox.vue`，粘贴模板
- [ ] 定义 props:
  ```typescript
  defineProps<{
    visible: boolean
    imageUrl: string
  }>()
  defineEmits<{
    close: []
    download: [url: string]
  }>()
  ```
- [ ] 在 Sessions.vue 模板中替换为:
  ```html
  <Lightbox :visible="!!lightboxUrl" :image-url="lightboxUrl" @close="lightboxUrl = ''" @download="downloadOne" />
  ```
- [ ] 从 Sessions.vue `<style scoped>` 中剪切 `.lightbox-overlay`, `.lightbox-content`, `.lightbox-close`, `.lightbox-img`, `.lightbox-actions` 六段样式到 `Lightbox.vue`

**验证:**
- [ ] `npm run build` 通过
- [ ] 点击图片 → lightbox 弹出 → 关闭按钮/遮罩关闭 → 下载按钮触发浏览器下载

**Commit:** `refactor(ui): extract Lightbox component from Sessions.vue`

---

### Task 1.2: CompareOverlay

**Files:**
- `frontend/src/components/session/CompareOverlay.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 199-210 剪切对比遮罩整段
- [ ] 创建 `CompareOverlay.vue`，props:
  ```typescript
  defineProps<{
    images: string[]
  }>()
  defineEmits<{
    close: []
    downloadAll: [urls: string[]]
  }>()
  ```
- [ ] Sessions.vue 替换为:
  ```html
  <CompareOverlay :images="comparingImages" @close="comparingImages = []" @download-all="downloadAll" />
  ```
- [ ] 迁移 `.compare-overlay`, `.compare-view`, `.compare-header`, `.compare-images`, `.compare-img` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] 勾选 2+ 张图 → 对比弹出 → 关闭/下载按钮功能不变

**Commit:** `refactor(ui): extract CompareOverlay component from Sessions.vue`

---

### Task 1.3: ContextMenu

**Files:**
- `frontend/src/components/session/ContextMenu.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 604-611 剪切两处 `context-menu` div
- [ ] 创建 `ContextMenu.vue`，合并两个实例为一个通用组件
- [ ] Props:
  ```typescript
  defineProps<{
    visible: boolean
    x: number
    y: number
    items: Array<{ label: string; action: string }>
  }>()
  defineEmits<{
    action: [action: string]
    close: []
  }>
  ```
- [ ] Sessions.vue 模板替换为两处调用:
  ```html
  <ContextMenu :visible="contextMenu.show" :x="contextMenu.x" :y="contextMenu.y"
    :items="[{ label: '重命名', action: 'rename' }, { label: '删除', action: 'delete' }]"
    @action="(a) => contextMenuAction(a as string)" @close="contextMenu.show = false" />
  <ContextMenu :visible="imageContextMenu.show" :x="imageContextMenu.x" :y="imageContextMenu.y"
    :items="contextMenuImageItems" @action="(a) => imageContextAction(a as string)" @close="imageContextMenu.show = false" />
  ```
- [ ] Sessions.vue script 新增:
  ```typescript
  const contextMenuImageItems = computed(() => [
    { label: isContextPinned(imageContextMenu.value.url) ? '从上下文移除' : '加入上下文', action: 'toggle' },
  ])
  function contextMenuAction(action: string) { /* ... 分派 rename/delete */ }
  function imageContextAction(action: string) { if (action === 'toggle') toggleContextPin(imageContextMenu.value.url) }
  ```
- [ ] 迁移 `.context-menu` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] 右键 session 列表项 → 重命名/删除菜单弹出且功能正常
- [ ] 右键图片 → 加入/移除上下文菜单弹出且功能正常

**Commit:** `refactor(ui): extract ContextMenu component from Sessions.vue`

---

### Task 1.4: GeneratingIndicator

**Files:**
- `frontend/src/components/session/GeneratingIndicator.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 178-190 剪切 generating 指示器部分
- [ ] 创建 `GeneratingIndicator.vue`，props:
  ```typescript
  defineProps<{
    text: string
    taskTypeLabel: string
    progressText: string
  }>()
  ```
- [ ] Sessions.vue 替换为:
  ```html
  <GeneratingIndicator :text="generatingText" :task-type-label="currentTaskLabel" :progress-text="getTaskProgress(currentSessionId)" />
  ```
- [ ] 迁移 `.generating-indicator`, `.dot`, `.generating-text`, `.task-type-badge`, `.task-progress` 样式及 `.dot` 动画

**验证:**
- [ ] `npm run build` 通过
- [ ] 发送生图请求 → 三点闪烁动画出现 → 任务类型标签显示 → 进度文字显示

**Commit:** `refactor(ui): extract GeneratingIndicator component from Sessions.vue`

---

## Phase 2: 输入区拆分 (2 个 Task)

### Task 2.1: ContextImageStrip

**Files:**
- `frontend/src/components/session/ContextImageStrip.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 237-251 剪切 `.refine-strip` 整段
- [ ] 创建 `ContextImageStrip.vue`，props/emits:
  ```typescript
  import type { ContextImage } from '../../types'
  
  defineProps<{
    images: ContextImage[]
  }>()
  defineEmits<{
    remove: [index: number]
    'add-image': [files: FileList]
  }>()
  ```
- [ ] Sessions.vue 模板替换为:
  ```html
  <ContextImageStrip v-if="contextImageList.length" :images="contextImageList" @remove="removeContextImage" @add-image="processMainFiles" />
  ```
- [ ] 迁移 `.refine-strip`, `.refine-strip-item`, `.refine-strip-thumb-wrap`, `.refine-strip-thumb`, `.refine-strip-badge`, `.refine-strip-label`, `.refine-add-btn` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] 上传图片 → context strip 出现缩略图 + 编号 badge → X 移除 → + 追加按钮正常

**Commit:** `refactor(ui): extract ContextImageStrip component from Sessions.vue`

---

### Task 2.2: ComposerControls (数量/尺寸/toggle/发送/精修头)

**Files:**
- `frontend/src/components/session/ComposerControls.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板中剪切三块:
  - 精修模式头 (line 233-236)
  - 数量/尺寸控件 (line 281-326)
  - 发送/智能/助手按钮 (line 327-343)
- [ ] 创建 `ComposerControls.vue`，props/emits:
  ```typescript
  defineProps<{
    agentMode: boolean
    isRefineMode: boolean
    isBusy: boolean
    imageCount: number
    customCount: boolean
    imageWidth: number
    imageHeight: number
    noSizeLimit: boolean
  }>()
  defineEmits<{
    'exit-refine': []
    'toggle-agent': []
    'toggle-assistant': []
    'send': []
    'cancel': []
    'update:imageCount': [value: number]
    'update:customCount': [value: boolean]
    'update:imageWidth': [value: number]
    'update:imageHeight': [value: number]
    'update:noSizeLimit': [value: boolean]
    'open-custom-count': []
    'clamp-count': []
  }>()
  ```
- [ ] 数量/尺寸控件的 `v-model` 改为通过 emit 双向绑定 (父组件 `v-model:image-count` 等)
- [ ] Sessions.vue 模板替换:
  ```html
  <ComposerControls
    :agent-mode="agentMode" :is-refine-mode="isRefineMode" :is-busy="currentSessionId && isSessionBusy(currentSessionId)"
    v-model:image-count="imageCount" v-model:custom-count="customCount"
    v-model:image-width="imageWidth" v-model:image-height="imageHeight" v-model:no-size-limit="noSizeLimit"
    @exit-refine="exitRefineMode" @toggle-agent="agentMode = !agentMode" @toggle-assistant="showAssistant = !showAssistant"
    @send="sendGenerate" @cancel="cancelAgent"
    @open-custom-count="openCustomCount" @clamp-count="clampCount"
  />
  ```
- [ ] 迁移 `.refine-header`, `.refine-label`, `.input-controls`, `.input-options`, `.count-btn`, `.count-input`, `.size-input`, `.size-sep`, `.no-limit-label`, `.input-actions` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] Agent/workbench 模式切换时数量/尺寸控件的显示/隐藏正确
- [ ] 发送按钮在 busy 时禁用，文字变为"任务进行中..."
- [ ] 取消按钮仅在 agent 模式 + busy 时显示
- [ ] 精修模式头显示 + 退出按钮

**Commit:** `refactor(ui): extract ComposerControls component from Sessions.vue`

---

## Phase 3: 消息区拆分 (6 个 Task)

每个消息卡片是纯展示组件 (无本地状态、无 API 调用)，`MessageList.vue` 是组装层。

### Task 3.1: TextMessageCard

**Files:**
- `frontend/src/components/session/TextMessageCard.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 54-56 (text) + line 127-129 (error) + line 173-175 (default) 合并为统一组件
- [ ] 创建 `TextMessageCard.vue`，props:
  ```typescript
  defineProps<{
    content: string
    messageType?: string
    role: string
    renderedContent: string  // 已 renderMarkdown 的内容由父组件传入
  }>()
  ```
- [ ] Sessions.vue 替换为:
  ```html
  <TextMessageCard v-if="msg.message_type === 'text' || msg.message_type === 'error' || (!['text','image','optimization','plan','agent','error'].includes(msg.message_type || ''))"
    :content="msg.content" :message-type="msg.message_type" :role="msg.role" :rendered-content="renderMarkdown(msg.content)" />
  ```
- [ ] 迁移 `.error-text` 样式 (text/default 无额外样式)

**验证:**
- [ ] `npm run build` 通过
- [ ] 文本消息渲染不变，error 消息红色显示不变

**Commit:** `refactor(ui): extract TextMessageCard component from Sessions.vue`

---

### Task 3.2: OptimizationCard

**Files:**
- `frontend/src/components/session/OptimizationCard.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 80-94 剪切 optimization 消息段
- [ ] 创建 `OptimizationCard.vue`，props/emits:
  ```typescript
  defineProps<{
    content: string
    renderedContent: string
    metadata: { original?: string; optimized?: string }
  }>()
  defineEmits<{
    'apply-optimized': [text: string]
    'apply-original': [text: string]
  }>()
  ```
- [ ] Sessions.vue 替换为:
  ```html
  <OptimizationCard v-if="msg.message_type === 'optimization'"
    :content="msg.content" :rendered-content="renderMarkdown(msg.content)"
    :metadata="(msg.metadata || {}) as { original?: string; optimized?: string }"
    @apply-optimized="applyOptimized" @apply-original="(t) => applyOptimized(t)" />
  ```
- [ ] 迁移 `.optimization-compare`, `.compare-side`, `.compare-label`, `.compare-text`, `.optimized` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] 优化消息的原始/优化后对比展示不变，应用优化/使用原始按钮功能不变

**Commit:** `refactor(ui): extract OptimizationCard component from Sessions.vue`

---

### Task 3.3: ImageMessageCard

**Files:**
- `frontend/src/components/session/ImageMessageCard.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 57-79 剪切 image 消息段
- [ ] 创建 `ImageMessageCard.vue`，props/emits:
  ```typescript
  defineProps<{
    content: string
    renderedContent: string
    metadata: { image_urls?: string[] }
    selectedUrls: string[]
  }>()
  defineEmits<{
    'update:selectedUrls': [urls: string[]]
    'open-image': [url: string]
    'show-context-menu': [event: MouseEvent, url: string]
    'download-selected': []
    'download-all': []
    'compare-selected': []
    'enter-refine': []
  }>()
  ```
- [ ] Sessions.vue 替换为:
  ```html
  <ImageMessageCard v-if="msg.message_type === 'image'"
    :content="msg.content" :rendered-content="renderMarkdown(msg.content)"
    :metadata="(msg.metadata || {}) as { image_urls?: string[] }"
    v-model:selected-urls="selectedImages"
    @open-image="openImage" @show-context-menu="(e, url) => showImageContextMenu(e, url)"
    @download-selected="downloadSelected" @download-all="downloadAll(msg.metadata?.image_urls || [])"
    @compare-selected="compareSelected" @enter-refine="enterRefineMode(msg)" />
  ```
- [ ] 迁移 `.image-grid`, `.image-item`, `.image-check`, `.image-actions` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] 图片网格展示、勾选框 (v-model 双向绑定)、下载/对比/精修按钮全部正常
- [ ] 右键图片 → context menu 弹出

**Commit:** `refactor(ui): extract ImageMessageCard component from Sessions.vue`

---

### Task 3.4: PlanMessageCard

**Files:**
- `frontend/src/components/session/PlanMessageCard.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 95-126 剪切 plan 消息段
- [ ] 创建 `PlanMessageCard.vue`，props/emits:
  ```typescript
  defineProps<{
    content: string
    renderedContent: string
    expanded: boolean
    steps: Array<{ prompt: string; description?: string; negative_prompt?: string }>
  }>()
  defineEmits<{
    'toggle': []
  }>()
  ```
- [ ] Sessions.vue 替换为:
  ```html
  <PlanMessageCard v-if="msg.message_type === 'plan'"
    :content="msg.content" :rendered-content="renderMarkdown(msg.content)"
    :expanded="expandedPlanIds.has(msg.id)"
    :steps="(msg.metadata?.steps || []) as any[]"
    @toggle="togglePlanCard(msg.id)" />
  ```
- [ ] 迁移 `.plan-card`, `.plan-card-header`, `.plan-card-title`, `.plan-card-meta`, `.plan-card-body`, `.plan-card-step`, `.plan-step-header`, `.plan-step-detail`, `.plan-step-count`, `.plan-chevron` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] Plan card 展开/折叠不变，步骤内容展示完整

**Commit:** `refactor(ui): extract PlanMessageCard component from Sessions.vue`

---

### Task 3.5: AgentMessageCard (复用 AgentStreamCard)

**分析:** Agent 消息的静态展示部分 (line 130-172) 可以新建 `AgentMessageCard.vue`；流式部分已有 `AgentStreamCard.vue` 且工作正常，不碰。

**Files:**
- `frontend/src/components/session/AgentMessageCard.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 130-172 剪切 agent 消息段
- [ ] 创建 `AgentMessageCard.vue`，props:
  ```typescript
  defineProps<{
    content: string
    renderedContent: string
    cost: number | undefined
    images: string[] | undefined
    steps: Array<Record<string, unknown>> | undefined
    expandedStepIds: Set<string>
    messageId: string
  }>()
  defineEmits<{
    'open-image': [url: string]
    'toggle-step': [stepKey: string]
  }>()
  ```
- [ ] Sessions.vue 替换为:
  ```html
  <AgentMessageCard v-if="msg.message_type === 'agent'"
    :content="msg.content" :rendered-content="renderMarkdown(msg.content)"
    :cost="(msg.metadata?.cost as number)"
    :images="(msg.metadata?.images as string[])"
    :steps="(msg.metadata?.steps as any[])"
    :expanded-step-ids="expandedStepIds"
    :message-id="msg.id"
    @open-image="openImage" @toggle-step="(k) => expandedStepIds.has(k) ? expandedStepIds.delete(k) : expandedStepIds.add(k)" />
  ```
- [ ] 迁移 `.agent-card`, `.agent-card-header`, `.agent-card-content`, `.agent-card-images`, `.agent-card-thumb`, `.agent-steps-v2`, `.step-card`, `.step-card-row`, `.step-card-body`, `.step-card-args`, `.step-card-content` 等 agent 相关样式

**验证:**
- [ ] `npm run build` 通过
- [ ] Agent 消息的静态展示 (badge, cost, 图片 thumb, steps) 不变
- [ ] Step 展开/折叠不变

**Commit:** `refactor(ui): extract AgentMessageCard component from Sessions.vue`

---

### Task 3.6: MessageList (组装层)

**Files:**
- `frontend/src/components/session/MessageList.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 44-197 剪切整个 `.messages` div
- [ ] 创建 `MessageList.vue`，整合 Task 3.1-3.5 所有卡片 + AgentStreamCard + GeneratingIndicator
- [ ] Props/Emits (汇总所有子卡片的 emits):
  ```typescript
  import type { AgentStreamState } from '../../types'
  
  defineProps<{
    messages: Array<Record<string, unknown>>
    currentSessionId: string | null
    expandedPlanIds: Set<string>
    expandedStepIds: Set<string>
    selectedImages: string[]
    isBusy: boolean
    generatingText: string
    taskTypeLabel: string
    progressText: string
    agentStreamState: AgentStreamState | null
  }>()
  defineEmits<{
    'update:selectedImages': [urls: string[]]
    'open-image': [url: string]
    'show-image-context': [event: MouseEvent, url: string]
    'download-selected': []
    'download-all': [urls: string[]]
    'compare-selected': []
    'enter-refine': [msg: Record<string, unknown>]
    'apply-optimized': [text: string]
    'apply-original': [text: string]
    'toggle-plan': [msgId: string]
    'toggle-step': [stepKey: string]
    'copy-message': [msg: Record<string, unknown>]
    'cancel-agent': []
  }>()
  ```
- [ ] Sessions.vue 模板替换为:
  ```html
  <MessageList
    :messages="messages" :current-session-id="currentSessionId"
    :expanded-plan-ids="expandedPlanIds" :expanded-step-ids="expandedStepIds"
    v-model:selected-images="selectedImages"
    :is-busy="!!(currentSessionId && isSessionBusy(currentSessionId))"
    :generating-text="generatingText" :task-type-label="currentTaskLabel"
    :progress-text="getTaskProgress(currentSessionId)"
    :agent-stream-state="agentStreamState"
    @open-image="openImage" @show-image-context="(e, url) => showImageContextMenu(e, url)"
    @download-selected="downloadSelected" @download-all="downloadAll"
    @compare-selected="compareSelected" @enter-refine="enterRefineMode"
    @apply-optimized="applyOptimized" @apply-original="(t) => applyOptimized(t)"
    @toggle-plan="(id) => expandedPlanIds.has(id) ? expandedPlanIds.delete(id) : expandedPlanIds.add(id)"
    @toggle-step="(k) => expandedStepIds.has(k) ? expandedStepIds.delete(k) : expandedStepIds.add(k)"
    @copy-message="copyMessageContent" @cancel-agent="cancelAgent"
  />
  ```
- [ ] 迁移 `.messages`, `.message`, `.message-content`, `.msg-copy-btn`, `.empty-state` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] 所有消息类型渲染完好 (text/image/optimization/plan/agent/error)
- [ ] 空 session 显示"选择或创建一个会话开始"
- [ ] Agent 流式卡片正常显示

**Commit:** `refactor(ui): extract MessageList composite from Sessions.vue`

---

## Phase 4: AssistantSidebar 拆分 (最大块)

这是最复杂的拆分，AssistantSidebar 内包含 4 个 Tab、API 调用、localStorage 持久化逻辑。

### Task 4.1: DialogTab

**Files:**
- `frontend/src/components/session/DialogTab.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 367-466 剪切 dialog tab 整段
- [ ] 创建 `DialogTab.vue`
- [ ] **拥有以下状态** (从 Sessions.vue script 移入):
  ```typescript
  const dialogInput = ref('')
  const dialogTextarea = ref<HTMLTextAreaElement | null>(null)
  const dialogContainer = ref<HTMLElement | null>(null)
  const dialogAttachments = ref<Attachment[]>([])
  const dragCounterDialog = ref(0)
  const isDragOverDialog = computed(() => dragCounterDialog.value > 0)
  const dialogToolCalls = ref<DialogToolCall[]>([])
  const responseStyle = ref<'default' | 'verbose' | 'concise'>('default')
  const showDialogSettings = ref(false)
  const searchEnabled = ref(false)
  ```
- [ ] Props (从父组件注入):
  ```typescript
  defineProps<{
    contextMode: 'shared' | 'current'
    memoryMode: 'global' | 'session'
    sessionId: string | null
    messages: Array<Record<string, unknown>>
    contextImageList: ContextImage[]
    dialogMessages: DialogMessage[]  // v-model
  }>()
  defineEmits<{
    'update:dialogMessages': [msgs: DialogMessage[]]
    'apply-optimized': [prompt: string]
    'save-dialog': []
    'clear-dialog': []
  }>()
  ```
- [ ] 拖拽处理函数 (`onDragEnterDialog`/`onDragOverDialog`/`onDragLeaveDialog`/`onDropDialog`) 移入 DialogTab
- [ ] `sendDialog` / `autoResizeDialogTextarea` / `handleDialogFileUpload` / `processDialogFiles` 移入 DialogTab
- [ ] `sendDialog` 内部调用 `promptApi.stream()` (R4: 允许子组件直接调 API)
- [ ] `watch(dialogMessages)` localStorage 持久化逻辑移入 DialogTab
- [ ] `watch(memoryMode)` 移入 DialogTab
- [ ] Sessions.vue 模板替换:
  ```html
  <DialogTab v-if="assistantTab === 'dialog'"
    :context-mode="contextMode" :memory-mode="memoryMode"
    :session-id="currentSessionId" :messages="messages"
    :context-image-list="contextImageList"
    v-model:dialog-messages="dialogMessages"
    @apply-optimized="applyOptimized"
    @save-dialog="saveDialogHistory" @clear-dialog="clearDialog" />
  ```
- [ ] 迁移 dialog 相关样式 (`.tab-dialog`, `.dialog-config-bar`, `.dialog-settings-panel`, `.dialog-messages`, `.dialog-msg`, `.dialog-input-area`, `.dialog-textarea`, `.dialog-actions`, `.tool-calls-area`, `.tool-call-card` 等)

**验证:**
- [ ] `npm run build` 通过
- [ ] 对话 tab 发送消息 → SSE 流式输出 → 工具调用卡片显示 → 搜索按钮切换
- [ ] localStorage 对话持久化/读取正常
- [ ] "共享上下文"/"仅当前输入"、"全局跨窗口"/"仅当前会话" 配置切换正常
- [ ] 应用优化按钮功能正常

**Commit:** `refactor(ui): extract DialogTab component from Sessions.vue`

---

### Task 4.2: OptimizeTab

**Files:**
- `frontend/src/components/session/OptimizeTab.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 468-504 剪切 optimize tab 整段
- [ ] 创建 `OptimizeTab.vue`
- [ ] **拥有以下状态**:
  ```typescript
  const selectedDirections = ref<string[]>([])
  const customInstruction = ref('')
  const optimizeResult = ref('')
  ```
- [ ] Props:
  ```typescript
  defineProps<{
    inputText: string  // 当前输入框的提示词
  }>()
  defineEmits<{
    'apply-optimized': [text: string]
  }>()
  ```
- [ ] `doOptimize` 函数移入 (调用 `promptApi.optimizeStream()`)
- [ ] `optimizing` ref 移入
- [ ] Sessions.vue 模板替换:
  ```html
  <OptimizeTab v-if="assistantTab === 'optimize'"
    :input-text="inputText" @apply-optimized="applyOptimized" />
  ```
- [ ] 迁移 `.tab-optimize`, `.optimize-directions`, `.direction-item`, `.direction-info`, `.optimize-preview`, `.optimize-result`, `.result-text`, `.streaming` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] 优化方向多选 → 自定义指令输入 → 点击优化 → 流式结果显示 → 应用优化到主输入框
- [ ] 优化方向 checkbox 行为不变

**Commit:** `refactor(ui): extract OptimizeTab component from Sessions.vue`

---

### Task 4.3: PlanTab

**Files:**
- `frontend/src/components/session/PlanTab.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 507-563 剪切 plan tab 整段
- [ ] 创建 `PlanTab.vue`
- [ ] **拥有以下状态**:
  ```typescript
  const selectedPlanStrategy = ref('parallel')
  const planTemplates = ref<PlanTemplate[]>([])
  const selectedTemplateId = ref('')
  const templateVariables = ref<TemplateVariable[]>([])
  const templateVariableValues = ref<Record<string, string>>({})
  const planSteps = ref<PlanStep[]>([])
  const planStreamText = ref('')
  const planning = ref(false)
  ```
- [ ] Props:
  ```typescript
  defineProps<{
    inputText: string
    noSizeLimit: boolean
    imageWidth: number
    imageHeight: number
  }>()
  defineEmits<{
    'execute-plan': [steps: PlanStep[], strategy: string]
    'save-template': [steps: PlanStep[], strategy: string]
  }>()
  ```
- [ ] `doPlan` / `loadTemplate` / `applyTemplateVariables` / `moveStep` / `duplicateStep` / `saveAsTemplate` 移入 PlanTab
- [ ] `planTemplateApi.list()` 在 `onMounted` 中调用 (R4: 允许)
- [ ] Sessions.vue 模板替换:
  ```html
  <PlanTab v-if="assistantTab === 'plan'"
    :input-text="inputText" :no-size-limit="noSizeLimit" :image-width="imageWidth" :image-height="imageHeight"
    @execute-plan="(steps, strategy) => { planSteps.value = steps; selectedPlanStrategy.value = strategy; executePlan() }"
    @save-template="saveAsTemplate" />
  ```
- [ ] 注意: `executePlan` 函数仍在 Sessions.vue (不移动)，`PlanTab` 只负责 emit 步骤数据。
- [ ] 迁移 `.tab-plan`, `.plan-template-section`, `.template-select`, `.template-variables`, `.plan-steps`, `.plan-step`, `.step-header`, `.step-actions`, `.plan-streaming`, `.stream-text` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] 模板下拉 → 选择模板 → 变量输入 → 应用变量 → 步骤填充
- [ ] 生成规划按钮 → 流式结果显示
- [ ] 步骤编辑 (上移/下移/复制/删除) → "确认并执行" → 调到后端
- [ ] "保存为模板"按钮正常

**Commit:** `refactor(ui): extract PlanTab component from Sessions.vue`

---

### Task 4.4: SkillTab

**Files:**
- `frontend/src/components/session/SkillTab.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 565-580 剪切 skill tab 整段
- [ ] 创建 `SkillTab.vue`
- [ ] Props:
  ```typescript
  defineProps<{
    skills: Skill[]
    selectedSkillIds: string[]
  }>()
  defineEmits<{
    'update:selectedSkillIds': [ids: string[]]
  }>()
  ```
- [ ] Sessions.vue 替换:
  ```html
  <SkillTab v-if="assistantTab === 'skill'"
    :skills="skills" v-model:selected-skill-ids="selectedSkillIds" />
  ```
- [ ] 迁移 `.tab-skills`, `.skill-item`, `.skill-label`, `.skill-info`, `.skill-name`, `.skill-desc`, `.empty-hint`, `.hint-text` 样式

**验证:**
- [ ] `npm run build` 通过
- [ ] 技能列表展示 → 勾选同步到 store → 勾选状态持久化

**Commit:** `refactor(ui): extract SkillTab component from Sessions.vue`

---

### Task 4.5: AssistantSidebar (容器)

**Files:**
- `frontend/src/components/session/AssistantSidebar.vue` (new)
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)

**Steps:**
- [ ] 从 Sessions.vue 模板 line 347-582 剪切整个 `.assistant-sidebar` div
- [ ] 创建 `AssistantSidebar.vue`，组装 4 个 Tab (DialogTab / OptimizeTab / PlanTab / SkillTab)
- [ ] **拥有以下状态**:
  ```typescript
  const assistantTab = ref('dialog')
  const assistantExpanded = ref(false)
  const contextMode = ref<'shared' | 'current'>('shared')
  const memoryMode = ref<'global' | 'session'>('global')
  const dialogMessages = ref<DialogMessage[]>([])
  ```
- [ ] Props:
  ```typescript
  defineProps<{
    visible: boolean
    sessionId: string | null
    messages: Array<Record<string, unknown>>
    inputText: string
    contextImageList: ContextImage[]
    noSizeLimit: boolean
    imageWidth: number
    imageHeight: number
    skills: Skill[]
    selectedSkillIds: string[]
  }>()
  defineEmits<{
    'close': []
    'apply-optimized': [text: string]
    'execute-plan': [steps: PlanStep[], strategy: string]
    'save-template': [steps: PlanStep[], strategy: string]
    'update:selectedSkillIds': [ids: string[]]
  }>()
  ```
- [ ] localStorage 恢复逻辑 (`savedMemoryMode` / `savedDialog`) 移入 AssistantSidebar 的 `<script setup>` 顶层
- [ ] Sessions.vue 模板替换为:
  ```html
  <AssistantSidebar v-if="showAssistant"
    :visible="showAssistant" :session-id="currentSessionId"
    :messages="messages" :input-text="inputText"
    :context-image-list="contextImageList"
    :no-size-limit="noSizeLimit" :image-width="imageWidth" :image-height="imageHeight"
    :skills="skills" v-model:selected-skill-ids="selectedSkillIds"
    @close="showAssistant = false"
    @apply-optimized="applyOptimized"
    @execute-plan="(steps, strategy) => { planSteps.value = steps; selectedPlanStrategy.value = strategy; executePlan() }"
    @save-template="saveAsTemplate" />
  ```
- [ ] 迁移 `.assistant-sidebar`, `.assistant-header`, `.assistant-tabs`, `.tab-btn`, `.assistant-header-actions`, `.assistant-content` 样式
- [ ] 从 Sessions.vue 删除已迁移的 `assistantTab`, `assistantExpanded`, `contextMode`, `memoryMode`, `dialogMessages`, `dialogMessages` watcher, `memoryMode` watcher, localStorage 恢复代码

**验证:**
- [ ] `npm run build` 通过
- [ ] 助手按钮打开/关闭 → 四个 Tab 切换正常 → 所有 Tab 行为不变
- [ ] localStorage 对话记忆/模式配置在刷新后恢复
- [ ] 切换 session 时 `memoryMode === 'session'` 的清除行为不变

**Commit:** `refactor(ui): extract AssistantSidebar composite from Sessions.vue`

---

## Phase 5: 收尾清理

### Task 5.1: Sessions.vue 清理

**Files:**
- `E:\LamImager\frontend\src\views\Sessions.vue` (edit)
- `E:\LamImager\frontend\src\types\index.ts` (edit — 已在 Task 0 完成)

**Steps:**
- [ ] 删除 Sessions.vue 中已移至子组件的 `<style scoped>` 块 (Phase 1-4 迁移的样式)
- [ ] 删除已移至子组件的 `ref()` / `computed()` / `watch()` 声明:
  - `assistantTab`, `assistantExpanded`, `contextMode`, `memoryMode`, `dialogMessages`, `dialogInput`, `dialogTextarea`, `dialogContainer`, `dialogAttachments`, `dialogToolCalls`, `responseStyle`, `showDialogSettings`, `searchEnabled`
  - `selectedDirections`, `customInstruction`, `optimizeResult`, `optimizing`
  - `selectedPlanStrategy`, `planTemplates`, `selectedTemplateId`, `templateVariables`, `templateVariableValues`, `planSteps`, `planStreamText`, `planning`
  - `dragCounterMain`, `isDragOverMain`, `dragCounterDialog`, `isDragOverDialog`, `mainTextarea` (如未在 ComposerControls 中使用)
  - `contextMenu` / `imageContextMenu` (如 ContextMenu 组件接管后不需要)
- [ ] 删除已移至子组件的函数:
  - `sendDialog`, `autoResizeDialogTextarea`, `handleDialogFileUpload`, `processDialogFiles`
  - `onDragEnterDialog`, `onDragOverDialog`, `onDragLeaveDialog`, `onDropDialog`
  - `doOptimize`
  - `doPlan`, `loadTemplate`, `applyTemplateVariables`, `moveStep`, `duplicateStep`, `saveAsTemplate`
  - `saveDialogHistory`, `clearDialog` (移至 AssistantSidebar)
  - `handleFileUpload`, `onDragEnterMain`, `onDragOverMain`, `onDragLeaveMain`, `onDropMain`, `processMainFiles` (保留，输入区仍需拖拽)
- [ ] 删除已移至子组件的 watcher:
  - `watch(dialogMessages, ...)`
  - `watch(memoryMode, ...)`
- [ ] 删除 localStorage 恢复代码 (line 779-789)
- [ ] 清理 `onMounted` — 移除不再需要的 `skillApi.list()`, `planTemplateApi.list()` 调用 (已移至子组件)
- [ ] 检查 Sessions.vue imports: 删除不再需要的 `skillApi`, `promptApi`, `planTemplateApi` import
- [ ] 确认 `assistantTabs` 常量已移除 (line 768-773)
- [ ] 确认 `optimizeDirections` 常量已移除 (line 798-804)
- [ ] 确认 `planStrategies` 常量已移除 (line 809-812)

**验证:**
- [ ] `npm run build` 通过
- [ ] 无 console error
- [ ] Sessions.vue 行数 < 2000
- [ ] 所有模式 (agent / workbench / 精修 / 助手) 完整回归:
  - 创建 session → 输入 prompt → 发送生成 → 图片展示
  - 上传参考图 → context strip 显示 → img2img 生成
  - Agent 模式 → 智能发送 → SSE 流式 → agent 消息卡
  - 助手对话框 → 发送/流式/工具调用/搜索
  - 助手优化 → 选择方向 → 流式结果 → 应用
  - 助手规划 → 模板选择 → 步骤编辑 → 执行
  - 图片 lightbox → 对比 → 精修模式

**Commit:** `refactor(ui): cleanup Sessions.vue after component extraction`

---

## 执行顺序

```
Task 0 (types) ─────────────────────────────────────────────┐
Phase 1: 1.1 → 1.2 → 1.3 → 1.4  (独立，零风险)              │
Phase 2: 2.1 → 2.2                (独立)                    │
Phase 3: 3.1 → 3.2 → 3.3 → 3.4 → 3.5 → 3.6  (串行)        │
Phase 4: 4.1 → 4.2 → 4.3 → 4.4 → 4.5   (串行)              │
Phase 5: 5.1                          (最后)                │
```

Phase 1 和 Phase 2 可并行推进 (无依赖)。Phase 3 依赖 Phase 1.4 (GeneratingIndicator 已提取)。Phase 4 依赖 Phase 3 完成。Phase 5 在全部完成后执行。

---

## 验证检查清单 (每个 Phase 完成后执行)

```bash
# 每完成一个 Phase 后运行
cd E:\LamImager\frontend
npm run build

# Phase 5 完成后额外运行
cd E:\LamImager\backend
python -c "from app.main import app; print('OK')"
```

### Smoketest 脚本 (Phase 5 完成后手动验证)

1. 启动应用 → 创建新会话 → 输入 "cat" → 点击"发送" → 图片生成
2. 上传一张本地图片 → 确认 context strip 显示 → img2img 生成
3. 点击"智能"按钮 → 输入 "画一只猫" → Agent 发送 → SSE 流式输出
4. 打开助手 → 对话 tab → 发送 "hello" → 流式回复
5. 助手 → 优化 tab → 选择方向 → 优化 → 应用
6. 助手 → 规划 tab → 生成规划 → 编辑步骤 → 执行
7. 点击生成图片 → lightbox 弹出 → 关闭
8. 勾选 2 张图片 → 对比 → 精修
9. 创建新 session → 确认对话历史在 `memoryMode=session` 时清除
10. 刷新页面 → 确认 `memoryMode=global` 时对话恢复
