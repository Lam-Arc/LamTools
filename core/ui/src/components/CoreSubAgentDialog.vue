<template>
  <Teleport defer :to="teleportTo">
    <dialog
      ref="dialogElement"
      :id="resolvedDialogId"
      class="core-sub-agent-dialog"
      :aria-labelledby="titleId"
      :aria-busy="run.status === 'running'"
      @cancel.prevent="requestClose"
    >
      <header class="core-sub-agent-dialog__header">
        <div class="core-sub-agent-dialog__identity">
          <h2 :id="titleId">{{ run.name }}</h2>
          <span class="core-sub-agent-dialog__status" :class="'is-' + run.status" role="status" aria-live="polite">
            {{ statusLabel(run.status) }}
          </span>
        </div>
        <button ref="closeButton" type="button" class="core-sub-agent-dialog__close" aria-label="关闭 Sub Agent" @click="requestClose">×</button>
      </header>

      <section
        ref="timelineElement"
        class="core-sub-agent-dialog__timeline"
        :aria-label="run.name + ' 时间线'"
        tabindex="0"
        @wheel.passive="timelineScroll.handleWheel"
        @scroll.passive="timelineScroll.handleScroll"
      >
        <ChatThread
          :messages="run.timeline"
          :assistant-label="run.name"
          :process-expanded-ids="expandedMessageIds"
          @toggle-process="toggleProcess"
          @decision-select="$emit('decision-select', $event)"
        >
          <template #empty>
            <slot name="empty">暂无可显示的 Sub Agent 事件。</slot>
          </template>
        </ChatThread>
      </section>

      <footer class="core-sub-agent-dialog__composer">
        <ComposerBar
          variant="embedded"
          :model-value="draft"
          :placeholder="placeholder"
          :textarea-aria-label="run.name + ' 输入框'"
          :disabled="disabled"
          :action-mode="actionMode"
          :send-label="sendLabel"
          :stop-label="stopLabel"
          @update:model-value="$emit('update:draft', $event)"
          @submit="$emit('submit')"
        >
          <template #preamble>
            <p v-if="errorText" class="core-sub-agent-dialog__error" role="alert">{{ errorText }}</p>
          </template>
          <template #tools>
            <CoreExecutionControls
              :model-value="selectedModelId"
              :thinking-mode="thinkingMode"
              :shallow-thinking-enabled="shallowThinkingEnabled"
              :model-options="modelOptions"
              :thinking-mode-options="thinkingModeOptions"
              model-aria-label="Sub Agent 模型"
              thinking-aria-label="Sub Agent 思考模式"
              @update:model-value="$emit('update:selectedModelId', $event)"
              @update:thinking-mode="$emit('update:thinkingMode', $event)"
              @update:shallow-thinking-enabled="$emit('update:shallowThinkingEnabled', $event)"
            />
          </template>
        </ComposerBar>
      </footer>
    </dialog>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import type { CoreSubAgentRun, MessagePartStatus } from '../types'
import type { CoreSelectOption, CoreThinkingModeOption } from '../composer/execution'
import { useCoreAutoFollowScroll } from '../composables/useCoreAutoFollowScroll'
import ChatThread from './ChatThread.vue'
import ComposerBar from './ComposerBar.vue'
import CoreExecutionControls from './CoreExecutionControls.vue'

const props = withDefaults(defineProps<{
  run: CoreSubAgentRun
  open?: boolean
  dialogId?: string
  teleportTo?: string
  draft?: string
  placeholder?: string
  disabled?: boolean
  actionMode?: 'send' | 'stop'
  sendLabel?: string
  stopLabel?: string
  selectedModelId?: string
  thinkingMode?: string
  shallowThinkingEnabled?: boolean
  modelOptions?: CoreSelectOption[]
  thinkingModeOptions?: CoreThinkingModeOption[]
  errorText?: string
}>(), {
  open: true,
  dialogId: '',
  teleportTo: '.workspace-shell',
  draft: '',
  placeholder: '向 Sub Agent 发送消息...',
  disabled: false,
  actionMode: 'send',
  sendLabel: 'send',
  stopLabel: 'stop',
  selectedModelId: '',
  thinkingMode: 'none',
  shallowThinkingEnabled: false,
  modelOptions: () => [],
  thinkingModeOptions: () => [{ value: 'none', label: '无思考' }],
  errorText: '',
})

const emit = defineEmits<{
  close: []
  submit: []
  'update:draft': [value: string]
  'update:selectedModelId': [value: string]
  'update:thinkingMode': [value: string]
  'update:shallowThinkingEnabled': [value: boolean]
  'decision-select': [payload: unknown]
}>()

const instanceId = useId().replace(/[^a-zA-Z0-9_-]/g, '')
const resolvedDialogId = computed(() => props.dialogId || 'core-sub-agent-dialog-' + instanceId)
const titleId = computed(() => resolvedDialogId.value + '-title')
const dialogElement = ref<HTMLDialogElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)
const timelineElement = ref<HTMLElement | null>(null)
const collapsedMessageIds = ref(new Set<string>())
const timelineScroll = useCoreAutoFollowScroll(timelineElement)
let timelineResizeObserver: ResizeObserver | null = null
let restoreFocus: HTMLElement | null = null

const expandedMessageIds = computed(() => new Set(
  props.run.timeline
    .filter(message => message.role === 'assistant' && !collapsedMessageIds.value.has(message.id))
    .map(message => message.id),
))

function toggleProcess(messageId: string) {
  const next = new Set(collapsedMessageIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  collapsedMessageIds.value = next
}

function requestClose() {
  emit('close')
}

function syncTimelineResizeObserver() {
  timelineResizeObserver?.disconnect()
  timelineResizeObserver = null
  const timeline = timelineElement.value
  if (!timeline || typeof ResizeObserver === 'undefined') return
  timelineResizeObserver = new ResizeObserver(() => {
    void timelineScroll.scrollToBottom()
  })
  timelineResizeObserver.observe(timeline)
  const thread = timeline.querySelector('.chat-thread')
  if (thread instanceof HTMLElement) timelineResizeObserver.observe(thread)
}

async function refreshTimeline(force = false) {
  await nextTick()
  syncTimelineResizeObserver()
  await timelineScroll.scrollToBottom(force)
}

async function showDialog() {
  await nextTick()
  const dialog = dialogElement.value
  if (!props.open || !dialog || dialog.open) return
  restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  if (typeof dialog.showModal === 'function') dialog.showModal()
  else dialog.setAttribute('open', '')
  await nextTick()
  closeButton.value?.focus()
  timelineScroll.autoFollow.value = true
  await refreshTimeline(true)
}

function hideDialog() {
  const dialog = dialogElement.value
  if (dialog?.open) {
    if (typeof dialog.close === 'function') dialog.close()
    else dialog.removeAttribute('open')
  }
  if (restoreFocus && isVisibleFocusTarget(restoreFocus)) {
    restoreFocus.focus()
  } else {
    document.querySelector<HTMLElement>('[data-workspace-right-toggle]')?.focus()
  }
  restoreFocus = null
}

function isVisibleFocusTarget(target: HTMLElement): boolean {
  if (!target.isConnected) return false
  const rect = target.getBoundingClientRect()
  const style = getComputedStyle(target)
  return rect.width > 0
    && rect.height > 0
    && style.display !== 'none'
    && style.visibility !== 'hidden'
    && style.pointerEvents !== 'none'
}

function statusLabel(status: MessagePartStatus): string {
  if (status === 'running') return '运行中'
  if (status === 'pending') return '等待中'
  if (status === 'error') return '失败'
  return '已完成'
}

watch(() => props.open, (open) => {
  if (open) void showDialog()
  else hideDialog()
})

watch(
  dialogElement,
  (dialog) => {
    if (dialog && props.open) void showDialog()
  },
  { flush: 'post' },
)

watch(() => props.run.subSessionId, () => {
  collapsedMessageIds.value = new Set()
  timelineScroll.autoFollow.value = true
  void refreshTimeline(true)
})

watch(
  () => props.run.timeline,
  () => void refreshTimeline(),
  { flush: 'post' },
)

onMounted(() => {
  syncTimelineResizeObserver()
  if (props.open) void showDialog()
})

onBeforeUnmount(() => {
  timelineResizeObserver?.disconnect()
  timelineResizeObserver = null
  hideDialog()
})
</script>

<style scoped>
.core-sub-agent-dialog:not([open]) {
  display: none;
}

.core-sub-agent-dialog {
  --text: var(--theme-main-text, #f2efeb);
  width: min(920px, calc(100vw - 40px));
  height: min(760px, calc(100dvh - 40px));
  max-width: none;
  max-height: none;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 14%, transparent);
  border-radius: 14px;
  background: var(--theme-main-background, #111);
  color: var(--theme-main-text, #f2efeb);
  padding: 0;
  animation: sub-agent-dialog-enter 180ms cubic-bezier(.25, 1, .5, 1);
}

.core-sub-agent-dialog[open] {
  display: grid;
}

.core-sub-agent-dialog::backdrop {
  background: rgb(0 0 0 / 55%);
}

.core-sub-agent-dialog__header {
  min-width: 0;
  min-height: 4rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text, currentColor) 10%, transparent);
  padding: .75rem 1rem .75rem 1.25rem;
}

.core-sub-agent-dialog__identity {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: .625rem;
}

.core-sub-agent-dialog__identity h2 {
  min-width: 0;
  overflow: hidden;
  margin: 0;
  color: inherit;
  font-size: 1rem;
  font-weight: 720;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-sub-agent-dialog__status {
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 58%, transparent);
  font-size: .75rem;
  font-weight: 650;
  line-height: 1.35;
  white-space: nowrap;
}

.core-sub-agent-dialog__status.is-running { color: var(--green, #5fca87); }
.core-sub-agent-dialog__status.is-pending { color: var(--orange, #e9a23b); }
.core-sub-agent-dialog__status.is-error { color: var(--red, #ef6b63); }

.core-sub-agent-dialog__close {
  position: relative;
  flex: 0 0 auto;
  width: 2rem;
  height: 2rem;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 64%, transparent);
  font: inherit;
  font-size: 1.25rem;
  line-height: 1;
  cursor: pointer;
}

.core-sub-agent-dialog__close::before {
  content: '';
  position: absolute;
  inset: -.375rem;
}

.core-sub-agent-dialog__close:hover {
  background: color-mix(in srgb, var(--theme-main-text, currentColor) 8%, transparent);
  color: var(--theme-main-text, currentColor);
}

.core-sub-agent-dialog__close:focus-visible,
.core-sub-agent-dialog__timeline:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--green, #5fca87) 62%, white 8%);
  outline-offset: 2px;
}

.core-sub-agent-dialog__timeline {
  min-height: 0;
  overflow: auto;
  padding: 1.25rem max(1.25rem, calc((100% - 760px) / 2));
  scrollbar-gutter: stable;
}

.core-sub-agent-dialog__timeline :deep(.chat-thread) {
  min-height: 100%;
}

.core-sub-agent-dialog__composer {
  min-width: 0;
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text, currentColor) 8%, transparent);
  padding: .75rem 1rem 1rem;
}

.core-sub-agent-dialog__error {
  margin: 0;
  padding: .5rem .75rem 0;
  color: var(--red, #ef6b63);
  font-size: .75rem;
  line-height: 1.45;
}

@keyframes sub-agent-dialog-enter {
  from { opacity: .78; transform: translateY(6px) scale(.99); }
  to { opacity: 1; transform: none; }
}

@media (max-width: 680px) {
  .core-sub-agent-dialog {
    width: 100vw;
    height: 100dvh;
    border: 0;
    border-radius: 0;
  }

  .core-sub-agent-dialog__header {
    padding-top: max(.75rem, env(safe-area-inset-top));
  }

  .core-sub-agent-dialog__timeline {
    padding: 1rem .875rem;
  }

  .core-sub-agent-dialog__composer {
    padding: .625rem .75rem max(.75rem, env(safe-area-inset-bottom));
  }

  .core-sub-agent-dialog__composer :deep(.ui-select-trigger),
  .core-sub-agent-dialog__composer :deep(.send) {
    min-height: 2.75rem;
    height: 2.75rem;
  }
}

@media (pointer: coarse) {
  .core-sub-agent-dialog__composer :deep(.ui-select-trigger),
  .core-sub-agent-dialog__composer :deep(.send) {
    min-height: 2.75rem;
    height: 2.75rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .core-sub-agent-dialog {
    animation: none;
  }
}
</style>
