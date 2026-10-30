<template>
  <div class="chat-thread" data-ui-id="chat.thread">
    <div v-if="messages.length === 0 && showEmptyState" class="sidebar-empty">
      <slot name="empty">
        <span>{{ t("暂无消息，发送一个任务。") }}</span>
      </slot>
    </div>

    <MessageView
      v-for="msg in messages"
      :key="msg.id"
      :data-message-id="msg.id"
      v-memo="[msg, assistantLabelForMessage(msg), processExpandedIds.has(msg.id), messageActions, messageTurnActive(msg), messageTurnStatus(msg), messageActiveTurnId(msg), lockedMessageIds.has(msg.id), autoPlotMath, decisionsDisabled]"
      :motion-enter="!initialMessageIds.has(msg.id)"
      :msg="msg"
        :assistant-label="assistantLabelForMessage(msg)"
        :process-expanded-ids="processExpandedIds"
        :message-actions="messageActions"
        :transport="transport"
      :project-id="projectId"
      :work-root="workRoot"
      :active-turn-id="messageActiveTurnId(msg)"
      :turn-active="messageTurnActive(msg)"
      :turn-status="messageTurnStatus(msg)"
      :locked-message-ids="lockedMessageIds"
      :auto-plot-math="autoPlotMath"
      :sub-agent-rows-inert="subAgentRowsInert"
      :decisions-disabled="decisionsDisabled"
      @toggle-process="onToggleProcess"
        @decision-select="onDecisionSelect"
        @fork-message="onForkMessage"
        @rollback-message="onRollbackMessage"
        @edit-message="onEditMessage"
        @open-sub-agent="onOpenSubAgent"
      >
        <template v-if="$slots['message-product']" #message-product="slotProps">
          <slot name="message-product" v-bind="slotProps" />
        </template>
        <template v-if="$slots['assistant-content']" #assistant-content="slotProps">
          <slot name="assistant-content" v-bind="slotProps" />
        </template>
        <template v-if="$slots['reasoning-content']" #reasoning-content="slotProps">
          <slot name="reasoning-content" v-bind="slotProps" />
        </template>
        <template v-if="$slots['message-footer']" #message-footer="slotProps">
          <slot name="message-footer" v-bind="slotProps" />
        </template>
      </MessageView>

      <PluginSystemContributions region="message" />
    <slot name="tail" />
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import type { CoreAttachment, CoreMessage } from '@/types.ts'
import type { LamToolsTransport } from '@/transport/index.ts'
import type { CoreSubAgentRef } from '@/agents/subAgentProjection.ts'
import { assistantSegmentTurnId } from '@/appServer/selectors.ts'
import MessageView from '@/components/MessageView.vue'
import PluginSystemContributions from '@/components/PluginSystemContributions.vue'

defineOptions({ name: 'ChatThread' })

defineSlots<{
  empty?: () => unknown
  tail?: () => unknown
  'message-product'?: (props: { message: CoreMessage }) => unknown
  'assistant-content'?: (props: { content: string; live?: boolean }) => unknown
  'reasoning-content'?: (props: { content: string; live?: boolean }) => unknown
  'message-footer'?: (props: { message: CoreMessage }) => unknown
}>()

const props = withDefaults(
  defineProps<{
    messages: CoreMessage[]
    /** Render the generic empty message when there are no messages. */
    showEmptyState?: boolean
    assistantLabel?: string
    /** Labels keyed by the model id frozen into each turn's runtime snapshot. */
    assistantModelLabels?: Readonly<Record<string, string>>
    /** Set of message ids whose process section is expanded */
    processExpandedIds?: Set<string>
    /** Show hover actions (copy / fork / roll back) under assistant replies */
    messageActions?: boolean
    /** Connection-neutral backend used for artifact bytes. */
    transport: LamToolsTransport
    /** Project id whose work_root contains the image artifact paths */
    projectId?: string | null
    /** Project work_root — enables direct local file reads in Tauri (asset protocol) */
    workRoot?: string | null
    /** 当前 active turn id（与 turnActive 搭配：消息属于运行中的 turn 时显示底部三圆点） */
    activeTurnId?: string | null
    /** 当前 turn 是否在运行（与 composer stop 按钮同一信号源） */
    turnActive?: boolean
    /** 当前 turn 的精确状态；耗时只在 running 时按墙钟推进。 */
    turnStatus?: string
    /** 最后一次上下文压缩边界之前的消息 id：编辑/分叉/回退入口在这些回合隐藏。 */
    lockedMessageIds?: Set<string>
    /** Automatically plot supported display-math formulas in final answers. */
    autoPlotMath?: boolean
    /** 面板内部：子代理行明确不可点（点击不抛事件、无障碍标注不可交互）。 */
    subAgentRowsInert?: boolean
    /** user:“多界面分屏”+(跨聊天过程可读，审批须在来源聊天处理)。 */
    decisionsDisabled?: boolean
  }>(),
  {
    showEmptyState: true,
    assistantLabel: 'Assistant',
    assistantModelLabels: () => ({}),
    processExpandedIds: () => new Set(),
    messageActions: false,
    projectId: null,
    workRoot: null,
    activeTurnId: null,
    turnActive: false,
    turnStatus: 'idle',
    lockedMessageIds: () => new Set(),
    autoPlotMath: false,
    subAgentRowsInert: false,
  },
)

function assistantLabelForMessage(message: CoreMessage): string {
  const runtimeModelId = typeof message.metadata?.runtime_model_id === 'string'
    ? message.metadata.runtime_model_id.trim()
    : ''
  if (!runtimeModelId) return props.assistantLabel
  return props.assistantModelLabels[runtimeModelId] || runtimeModelId.toUpperCase()
}

// user:“我发消息的一瞬间也是”“修，不要出错”+(运行状态只影响本轮助手消息；
// 历史消息与用户消息保持稳定，锁定集合按本条成员关系参与缓存，避免整段历史重绘)。
function messageTurnActive(message: CoreMessage): boolean {
  return props.turnActive && message.role === 'assistant' && Boolean(props.activeTurnId)
    && assistantSegmentTurnId(message.id) === props.activeTurnId
}

function messageActiveTurnId(message: CoreMessage): string | null {
  return messageTurnActive(message) ? props.activeTurnId : null
}

function messageTurnStatus(message: CoreMessage): string {
  return messageTurnActive(message) ? props.turnStatus : 'idle'
}

const emit = defineEmits<{
  'toggle-process': [messageId: string]
  'decision-select': [payload: { partId: string; option: DecisionOption; response: string }]
  'fork-message': [payload: AssistantActionPayload]
  'rollback-message': [payload: AssistantActionPayload]
  'edit-message': [payload: EditMessagePayload]
  'open-sub-agent': [ref: CoreSubAgentRef]
}>()

interface DecisionOption {
  id: string
  label: string
  description?: string
  response?: string
}

interface AssistantActionPayload {
  turnId: string
  content: string
}

interface EditMessagePayload {
  turnId: string
  content: string
  /** 原消息附件（已上传，随编辑重新发送，无需重新上传） */
  attachments?: CoreAttachment[]
}

// Stable function references (not inline arrows) so MessageView props keep
// their identity across parent re-renders — inline handlers would force every
// message to re-render on every stream tick.
function onToggleProcess(messageId: string): void {
  emit('toggle-process', messageId)
}

function onDecisionSelect(payload: { partId: string; option: DecisionOption; response: string }): void {
  emit('decision-select', payload)
}

function onForkMessage(payload: AssistantActionPayload): void {
  emit('fork-message', payload)
}

function onRollbackMessage(payload: AssistantActionPayload): void {
  emit('rollback-message', payload)
}

function onEditMessage(payload: EditMessagePayload): void {
  emit('edit-message', payload)
}

function onOpenSubAgent(ref: CoreSubAgentRef): void {
  emit('open-sub-agent', ref)
}

// ── 消息入场动效（motion-enter prop）：初始批次（挂载时已在列表中的消息）不播，
//    之后新到达的消息（新 turn 的用户消息/助手回复）挂载时淡入。集合在 setup
//    期捕获、只读，不引入任何流式 tick 响应式状态，v-memo 依赖不变。
//    注意：不能做成 directive 挂在 MessageView 上——该组件是多根（div + Teleport），
//    运行时 directive 不生效（Vue warn），动画在 MessageView 内部 onMounted 执行。
const initialMessageIds = new Set(props.messages.map((m) => m.id))
</script>

<style>
/* Message rendering styles are global (see MessageView.vue); this component
   keeps the historical style block so the chat-thread container chrome and
   the shared part styles keep their exact previous cascade. */
</style>
<style src="../styles/chat-thread-shell.css"></style>
<style src="../styles/chat-thread-tools.css"></style>
<style src="../styles/chat-thread-cards.css"></style>
<style src="../styles/chat-thread-process.css"></style>
<style src="../styles/chat-thread-reasoning.css"></style>
<style src="../styles/chat-thread-editing.css"></style>

