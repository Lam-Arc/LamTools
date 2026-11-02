<script setup lang="ts">
/**
 * Ping 会话卡片：一个会话一张卡，行为与主内容区同源。
 *
 * user:“它出来的那个对话卡片里面有没有复用我们主内容区的样式和行为？不应该自己新建一套”
 * user:“全部都不要新建，样式待会单独说明，现在先去给其他的对齐”
 * +(检查结论：此前卡片里手写了审批映射、裸 textarea 输入区和 MessageView 简化装配，
 *   与主界面已经分叉。本轮全部替换为主界面同款实现——ChatThread 渲染消息
 *   （消息操作/过程展开/锁定集合同源）、ComposerBar + InlineFileComposer +
 *   CoreSendStopButton 组成输入区（回车发送、运行中变停止、暂停变继续）、
 *   决策提交走通道上的共享审批控制器、分叉/回退/编辑走与主界面相同的
 *   session.fork / session.rollback 线协议。样式本轮不动，待样式轮统一。)
 */
import { computed, ref, watch } from 'vue'
import { Pin, PinOff } from 'lucide-vue-next'
import ChatThread from '@/components/ChatThread.vue'
import ComposerBar from '@/components/ComposerBar.vue'
import InlineFileComposer from '@/components/InlineFileComposer.vue'
import CoreSendStopButton from '@/components/CoreSendStopButton.vue'
import CoreExecutionControls from '@/components/CoreExecutionControls.vue'
import AttachmentSourceMenu from '@/components/AttachmentSourceMenu.vue'
import type { CoreExecutionControlsState } from '@/composables/useCoreExecutionControlsState.ts'
import type { CoreExecutionModelSource, CoreExecutionProviderSource } from '@/composer/execution.ts'
import { t } from '@/i18n/index.ts'
import type { CoreInputItem, CoreMessage } from '@/types.ts'
import type { CardState, PingRuntime } from '../ping/usePingRuntime.ts'

// user:“输入框缺东西”+(输入参数组与主界面同一套控件：模型/思考/模式/权限，
// 由宿主提供共享的执行控制状态，卡片只负责放进 composer 的 tools 位。)
type ExecutionControls = CoreExecutionControlsState<CoreExecutionModelSource, CoreExecutionProviderSource>

// user:"ping 环跟桌宠应当是解耦的，它们是两个独立的功能"+
// (Ping 会话卡片只依赖 Ping 运行时（ping/），不引用桌宠运行时与宠物实例。)
const props = defineProps<{
  ping: PingRuntime
  card: CardState
  /** 卡片即窗口：拖标题栏移动原生窗口、不显示钉住按钮、铺满窗口。 */
  standalone?: boolean
  /** 主界面同款输入参数组（模型/思考/模式/权限）。 */
  execution?: ExecutionControls | null
}>()

const modeOptions = computed(() => [
  { value: 'consider', get label() { return t('思索') } },
  { value: 'execute', get label() { return t('执行') } },
])

const channel = computed(() => props.ping.host.value?.get(props.card.sessionId) || null)
const messages = computed<CoreMessage[]>(() => channel.value?.messages().value || [])
const decisions = computed(() => channel.value?.decisions().value || [])
const turnStatus = computed(() => channel.value?.turnStatus().value || 'idle')
const turnActive = computed(() => channel.value?.turnActive().value || false)
const activeTurnId = computed(() => channel.value?.activeTurnId().value || '')
const lockedMessageIds = computed(() => channel.value?.lockedMessageIds().value || new Set<string>())
const processExpandedIds = computed(() => channel.value?.processExpandedIds().value || new Set<string>())
const hasMoreHistory = computed(() => channel.value?.hasMoreHistory().value || false)
const draft = ref(props.card.draft)
const sending = ref(false)
const error = ref('')
const scroller = ref<HTMLElement | null>(null)

watch(draft, value => { props.card.draft = value })

watch([messages, turnActive], () => {
  // 新消息滚到底：卡片内部自己滚动，不改变主窗口的滚动状态。
  requestAnimationFrame(() => {
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  })
}, { flush: 'post' })

// 滚动到顶部自动加载更早消息：通道消息按主界面同款投影做了窗口化。
async function onScroll(): Promise<void> {
  const node = scroller.value
  if (!node || node.scrollTop > 0) return
  if (!hasMoreHistory.value) return
  channel.value?.loadMoreHistory()
}

// 发送/停止/继续与主界面 submitComposer 相同的模式判定与处理顺序。
const composerMode = computed<'send' | 'stop' | 'resume'>(() => {
  if (turnActive.value) return 'stop'
  return turnStatus.value === 'paused' ? 'resume' : 'send'
})

const busy = computed(() => sending.value || !channel.value)

function onEditorKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    if (!busy.value) void submit()
  }
}

async function submit(): Promise<void> {
  const node = channel.value
  if (!node || sending.value) return
  error.value = ''
  // 停止/继续模式先于空文本守卫处理，否则停止请求永远发不出去（主界面同序）。
  if (composerMode.value === 'stop') {
    try {
      await node.stop()
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
    return
  }
  if (composerMode.value === 'resume') {
    sending.value = true
    try {
      const text = draft.value.trim()
      const items: CoreInputItem[] = text ? [{ type: 'text', text }] : []
      await node.resumeTurn(items)
      draft.value = ''
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      sending.value = false
    }
    return
  }
  await send()
}

async function send(): Promise<void> {
  const node = channel.value
  if (!node) return
  const text = draft.value.trim()
  const attachments = props.card.pendingAttachments
  if (!text && attachments.length === 0) return
  sending.value = true
  error.value = ''
  try {
    const client = props.ping.client.value
    if (!client) throw new Error('会话通道未就绪')
    const items = attachments.map(upload => client.attachmentInput(upload))
    // user:“输入框缺东西”+(与主界面同一套输入参数组：模型/思考/模式/权限随发送提交)
    const result = await node.send(text, items, props.execution?.turnOptions() || {})
    draft.value = ''
    props.card.pendingAttachments = []
    props.ping.pending.attach = null
    if (result.status === 'ignored') error.value = result.message
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    sending.value = false
  }
}

function removeAttachment(): void {
  props.card.pendingAttachments = []
  props.ping.pending.attach = null
}

// 决策提交直接转交通道上的共享审批控制器（useCoreApprovalController）：
// 映射、重复提交去重、通道检查都与主界面同一份实现。
async function onDecisionSelect(payload: { partId: string; option: { id?: string; label?: string }; response: string }): Promise<void> {
  const node = channel.value
  if (!node) return
  try {
    await node.handleDecision(payload as Parameters<typeof node.handleDecision>[0])
    error.value = node.approvalError
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

// 分叉/回退/编辑：与主界面同一条线协议（session.fork / session.rollback），
// 并保持相同的运行中守卫语义；分叉后在卡片里打开新会话（等价主界面的跳转）。
async function onFork(payload: { turnId: string; content: string }): Promise<void> {
  const node = channel.value
  if (!node) return
  if (turnActive.value) {
    error.value = t('任务运行中，请先停止任务再分叉')
    return
  }
  try {
    const forkedSessionId = await node.forkTurn(payload.turnId)
    if (forkedSessionId) props.ping.ensureCard(props.card.projectId, forkedSessionId)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function onRollback(payload: { turnId: string; content: string }): Promise<void> {
  const node = channel.value
  if (!node) return
  if (turnActive.value) {
    error.value = t('任务运行中，请先停止任务再回退')
    return
  }
  // 主界面用应用内确认框；卡片暂用浏览器确认，确认框样式待样式轮统一。
  if (!window.confirm(t('撤回这条消息及其之后的对话？'))) return
  try {
    await node.rollbackTurn(payload.turnId)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function onEdit(payload: { turnId: string; content: string; attachments?: Array<{ id: string }> }): Promise<void> {
  const node = channel.value
  if (!node) return
  if (turnActive.value) {
    error.value = t('任务运行中，请先停止任务再编辑')
    return
  }
  if (!payload.turnId) {
    error.value = t('这条消息没有可用的回合')
    return
  }
  try {
    // 编辑 = 回退后按原内容重发（主界面同语义）；原附件已上传，
    // 直接按 attachment_id 随发送提交，无需重新上传。
    await node.rollbackTurn(payload.turnId)
    const items: CoreInputItem[] = (payload.attachments || []).map(attachment => ({
      type: 'attachment',
      attachment_id: attachment.id,
    }))
    const result = await node.send(payload.content, items)
    if (result.status === 'ignored') error.value = result.message
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

// 卡片自身定位：只有标题栏能拖（CARD-08），位置经 ping.moveCard 统一夹回可视区。
const dragging = ref<{ offsetX: number; offsetY: number } | null>(null)

function scaleFactor(): number {
  return Math.max(0.1, props.ping.overlay.width / Math.max(1, window.innerWidth))
}

function startDrag(event: PointerEvent): void {
  // user:“卡片即窗口，把 ping 和桌宠拆分开”+(独立窗口模式拖标题栏就是拖窗口本身)
  if (props.standalone) {
    void (async () => {
      try {
        const { getCurrentWindow } = await import('@tauri-apps/api/window')
        await getCurrentWindow().startDragging()
      } catch {
        /* 非 Tauri 环境（测试/预览）忽略 */
      }
    })()
    return
  }
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  dragging.value = { offsetX: event.clientX - rect.left, offsetY: event.clientY - rect.top }
  ;(event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId)
}

function onDrag(event: PointerEvent): void {
  const state = dragging.value
  if (!state) return
  props.ping.moveCard(
    props.card.sessionId,
    event.clientX - state.offsetX + props.ping.overlay.x / scaleFactor(),
    event.clientY - state.offsetY + props.ping.overlay.y / scaleFactor(),
  )
}

function endDrag(): void {
  dragging.value = null
}
</script>

<template>
  <section
    class="pet-card"
    :class="{ 'pet-card--window': standalone }"
    data-region="ping-card"
    :data-session="card.sessionId"
  >
    <header
      class="pet-card__bar"
      @pointerdown="startDrag"
      @pointermove="onDrag"
      @pointerup="endDrag"
      @pointercancel="endDrag"
    >
      <!-- 会话标题做成标签页：与分屏标签同一套形状和选中底色。 -->
      <span class="pet-card__tab" data-pet-hit>
        <span class="pet-card__dot" :class="{ 'pet-card__dot--live': turnActive }" />
        <span class="pet-card__title" :title="card.sessionId">{{ card.title }}</span>
      </span>
      <div class="pet-card__actions" @pointerdown.stop>
        <!-- 钉子：独立窗口里控制是否置顶；共享卡片里用来钉住/取消钉住。 -->
        <button
          type="button"
          class="pet-card__action"
          :title="standalone
            ? (card.pinned ? '取消置顶' : '置顶窗口')
            : (card.pinned ? '取消钉住（回到共享标签）' : '钉住，成为独立卡片')"
          @pointerdown.stop
          @click="card.pinned ? ping.unpinCard(card.sessionId) : ping.pinCard(card.sessionId)"
        >
          <Pin v-if="card.pinned" :size="14" aria-hidden="true" />
          <PinOff v-else :size="14" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="pet-card__action"
          title="关闭视图（不会取消任务）"
          @pointerdown.stop
          @click="ping.closeCard(card.sessionId)"
        >✕</button>
      </div>
    </header>

    <div ref="scroller" class="pet-card__body" @scroll.passive="onScroll">
      <div v-if="!channel" class="pet-card__hint">会话通道未建立</div>
      <ChatThread
        v-else
        :messages="messages"
        :transport="ping.client.value!.transport"
        :project-id="card.projectId"
        :work-root="channel.workRoot ?? null"
        :active-turn-id="activeTurnId"
        :turn-active="turnActive"
        :turn-status="turnStatus"
        :locked-message-ids="lockedMessageIds"
        message-actions
        :process-expanded-ids="processExpandedIds"
        :sub-agent-rows-inert="true"
        @toggle-process="(messageId: string) => channel?.toggleProcess(messageId)"
        @decision-select="onDecisionSelect"
        @fork-message="onFork"
        @rollback-message="onRollback"
        @edit-message="onEdit"
      />
      <div v-if="decisions.length > 0" class="pet-card__pending">
        待处理 {{ decisions.length }} 项（可用审批按钮直接处理）
      </div>
    </div>

    <div v-if="card.pendingAttachments.length" class="pet-card__attach">
      <span v-for="attachment in card.pendingAttachments" :key="attachment.id" class="pet-card__chip">
        {{ attachment.filename }}
        <button type="button" class="pet-card__chip-remove" title="移除附件" @click="removeAttachment">✕</button>
      </span>
      <span class="pet-card__attach-hint">待发送，不会自动提交</span>
    </div>

    <ComposerBar
      v-model="draft"
      variant="embedded"
      class="pet-card__composer"
      :action-mode="composerMode"
      :disabled="busy"
      @submit="submit"
    >
      <template #textarea>
        <InlineFileComposer
          v-model="draft"
          :disabled="busy"
          placeholder="给 Sunday 发送任务…"
          @keydown="onEditorKeydown"
        />
      </template>
      <!-- user:“输入框缺东西”+(输入参数组：附件入口、模式/权限、模型/思考，与主界面同款控件) -->
      <template v-if="execution" #tools>
        <CoreExecutionControls
          :model-value="execution.selectedModelId.value"
          :model-options="execution.modelOptions.value"
          :thinking-mode="execution.selectedThinkingMode.value"
          :thinking-mode-options="execution.thinkingModeOptions.value"
          :shallow-thinking-enabled="execution.shallowThinkingEnabled.value"
          :active-mode="execution.activeMode.value"
          :mode-options="modeOptions"
          :permission-preset="execution.permissionPreset.value"
          @update:model-value="execution.selectModel($event)"
          @update:thinking-mode="execution.selectThinkingMode($event)"
          @update:shallow-thinking-enabled="execution.selectShallowThinking($event)"
          @update:active-mode="execution.selectMode($event)"
          @update:permission-preset="execution.selectPermissionPreset($event)"
        >
          <template #leading>
            <AttachmentSourceMenu :disabled="true" />
          </template>
        </CoreExecutionControls>
      </template>
      <template #action>
        <CoreSendStopButton
          :action-mode="composerMode"
          :disabled="busy || (composerMode === 'send' && !draft.trim() && card.pendingAttachments.length === 0)"
          :hold-enabled="false"
        />
      </template>
    </ComposerBar>

    <div v-if="error" class="pet-card__error">{{ error }}</div>
  </section>
</template>

<style scoped>
.pet-card {
  /* user:“先原状复刻”+“复刻这个词用得不好，应该叫做复用”+(卡片窗口的聊天面板
     原样复用主界面主内容面板的样式来源：主区域底色/图片层/毛玻璃滤镜/边框/
     文字色全部读主题算好的变量，不另立一套。) */
  position: relative;
  display: flex;
  flex-direction: column;
  width: 380px;
  max-height: 460px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--theme-main-border);
  background: var(--theme-main-background);
  background-image: var(--theme-main-image, none);
  background-size: var(--theme-main-image-size, auto);
  background-repeat: var(--theme-main-image-repeat, no-repeat);
  background-position: center;
  -webkit-backdrop-filter: var(--theme-main-glass-filter, none);
  backdrop-filter: var(--theme-main-glass-filter, none);
  --text: var(--theme-main-text);
  color: var(--text);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  pointer-events: auto;
}

/* 卡片即窗口：铺满整个窗口。外轮廓不再由页面画圆角，
   交给 Windows 给窗口的默认圆角（与 Sunday 主窗口一致）。
   user:“里面的样式不需要带圆角，用窗口系统自带的圆角就行” */
.pet-card--window {
  width: 100%;
  height: 100%;
  max-height: none;
  border-radius: 0;
}

/* user:“输入框的位置没对上”+(嵌入式输入栏的几何由托管方负责：沿用辅助对话
   托管 ComposerBar 的同一套规则——宽度交给容器、四周留出与消息区一致的外边距，
   输入卡不再贴住卡片边缘与圆角。) */
.pet-card > .pet-card__composer {
  flex: 0 0 auto;
  box-sizing: border-box;
  width: auto;
  margin: var(--space-2) var(--space-3) var(--space-3);
}

.pet-card__bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  cursor: grab;
  background: var(--theme-main-soft-background);
  border-bottom: 1px solid var(--theme-main-border);
  user-select: none;
}

.pet-card__bar:active {
  cursor: grabbing;
}

/* user:“我红框标的这一块，你把它改成标签页，并且把它的高度缩矮一点”+
   (标题区改成与分屏标签同款的小标签：选中底色、圆角、12px 字号；整条标题栏
   上下内边距收窄，高度随之变矮。) */
.pet-card__tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  max-width: min(72%, 240px);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  color: var(--text);
}

.pet-card__dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: color-mix(in srgb, var(--text) 35%, transparent);
}

.pet-card__dot--live {
  background: var(--green);
}

.pet-card__title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 600;
}

/* user:“那个空闲也不用有了，改成一个钉子”+(右侧状态文字换成钉子图标；独立窗口
   本身就是固定卡片，用静态钉子表示。) */
.pet-card__actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.pet-card__action {
  border: none;
  background: transparent;
  color: inherit;
  font-size: var(--type-sm);
  cursor: pointer;
  padding: var(--space-1);
  border-radius: var(--radius-sm);
}

.pet-card__action:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.pet-card__action:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.pet-card__body {
  flex: 1;
  min-height: 120px;
  overflow-y: auto;
  padding: var(--space-2) var(--space-3);
  font-size: var(--type-md);
}

.pet-card__hint,
.pet-card__pending {
  padding: var(--space-1);
  font-size: var(--type-xs);
  color: color-mix(in srgb, var(--text) 65%, transparent);
}

.pet-card__attach {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3) 0;
}

.pet-card__chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  border-radius: 999px;
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  font-size: var(--type-xs);
}

.pet-card__chip-remove {
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: var(--type-2xs);
}

.pet-card__attach-hint {
  font-size: var(--type-2xs);
  color: color-mix(in srgb, var(--text) 45%, transparent);
}

.pet-card__error {
  padding: 0 var(--space-3) var(--space-2);
  font-size: var(--type-xs);
  color: var(--red);
}
</style>
