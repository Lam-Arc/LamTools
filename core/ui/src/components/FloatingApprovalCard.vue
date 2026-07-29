<template>
  <Transition name="float-approval">
    <div
      v-if="visible && currentDecision"
      class="floating-approval-card"
      role="alert"
      aria-live="assertive"
      @keydown.escape="dismiss"
    >
      <div class="float-approval-header">
        <span class="float-approval-icon" aria-hidden="true">&#x1F6E1;&#xFE0F;</span>
        <span class="float-approval-title">{{ decisionTitle(currentDecision.part) }}</span>
        <button
          class="float-approval-close"
          type="button"
          aria-label="忽略此审批"
          title="忽略（可稍后在对话中处理）"
          @click="dismiss"
        >&times;</button>
      </div>

      <p v-if="decisionDetail(currentDecision.part)" class="float-approval-detail">
        {{ decisionDetail(currentDecision.part) }}
      </p>

      <div v-if="pendingCount > 1" class="float-approval-count">
        还有 {{ pendingCount - 1 }} 个待处理审批
      </div>

      <div class="float-approval-actions">
        <button
          class="float-approval-btn float-approval-btn--approve"
          type="button"
          @click="handleApprove"
        >批准执行</button>
        <button
          class="float-approval-btn float-approval-btn--deny"
          type="button"
          @click="handleDeny"
        >拒绝执行</button>
        <button
          class="float-approval-btn float-approval-btn--dismiss"
          type="button"
          @click="dismiss"
        >忽略</button>
      </div>

      <div class="float-approval-hint">
        按 <kbd>Esc</kbd> 忽略 · 审批卡仍在对话中可见
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { MessagePart } from '../types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PendingDecision {
  messageId: string
  part: MessagePart
}

interface DecisionOption {
  id: string
  label: string
  description?: string
  response?: string
}

// ---------------------------------------------------------------------------
// Props & Emits
// ---------------------------------------------------------------------------

const props = withDefaults(
  defineProps<{
    pendingDecisions: PendingDecision[]
    /** When true, the component has been explicitly dismissed by the user */
  }>(),
  {},
)

const emit = defineEmits<{
  'decision-select': [payload: { partId: string; option: DecisionOption; response: string }]
}>()

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** Tracks which decision partIds have been explicitly dismissed by the user in this session */
const dismissedIds = ref<Set<string>>(new Set())

/** Resets dismissedIds when a new set of pending decisions arrives (different from tracked) */
const trackedPendingKeys = ref<string>('')

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const pendingCount = computed(() => props.pendingDecisions.length)

/**
 * Filter out decisions that the user has explicitly dismissed in this session.
 * We still exclude them so they don't re-appear.
 */
const activeDecisions = computed(() =>
  props.pendingDecisions.filter((d) => !dismissedIds.value.has(d.part.id)),
)

/** Show the first non-dismissed pending decision */
const currentDecision = computed(() => activeDecisions.value[0] ?? null)

/** Visible when there is at least one non-dismissed pending decision */
const visible = computed(() => currentDecision.value !== null)

// ---------------------------------------------------------------------------
// Watchers
// ---------------------------------------------------------------------------

// When pending decisions change to a completely new set (e.g. new turn),
// reset dismissedIds so new approvals appear.
watch(
  () => props.pendingDecisions.map((d) => d.part.id).join(','),
  (newKey) => {
    if (newKey !== trackedPendingKeys.value) {
      trackedPendingKeys.value = newKey
      if (newKey.length === 0) {
        dismissedIds.value = new Set()
      }
    }
  },
)

// ---------------------------------------------------------------------------
// Keyboard handling
// ---------------------------------------------------------------------------

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && visible.value) {
    dismiss()
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
})

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function dismiss() {
  if (!currentDecision.value) return
  dismissedIds.value = new Set([...dismissedIds.value, currentDecision.value.part.id])
}

function handleApprove() {
  if (!currentDecision.value) return
  const part = currentDecision.value.part
  const options = decisionOptions(part)
  const approveOption = options.find((o) => o.id === 'approve' || o.id.includes('approve') || o.id.includes('批准')) || options[0]
  const response = buildResponse(part, approveOption)
  emit('decision-select', {
    partId: part.id,
    option: approveOption,
    response,
  })
  dismissedIds.value = new Set([...dismissedIds.value, part.id])
}

function handleDeny() {
  if (!currentDecision.value) return
  const part = currentDecision.value.part
  const options = decisionOptions(part)
  const denyOption = options.find((o) => o.id === 'deny' || o.id.includes('deny') || o.id.includes('拒绝')) || options[options.length - 1] || { id: 'deny', label: '拒绝执行' }
  const response = buildResponse(part, denyOption)
  emit('decision-select', {
    partId: part.id,
    option: denyOption,
    response,
  })
  dismissedIds.value = new Set([...dismissedIds.value, part.id])
}

// ---------------------------------------------------------------------------
// Decision helpers (replicated from ChatThread for self-contained rendering)
// ---------------------------------------------------------------------------

function decisionTitle(part: MessagePart): string {
  const args = (part.toolArgs || {}) as Record<string, unknown>
  const meta = (part.metadata || {}) as Record<string, unknown>
  const title = args.title || args.question || meta.title || meta.question || part.label
  return title ? `需要确认：${compactDetail(String(title), 48)}` : '等待确认'
}

function decisionDetail(part: MessagePart): string {
  const args = (part.toolArgs || {}) as Record<string, unknown>
  const meta = (part.metadata || {}) as Record<string, unknown>
  const detail = args.reason || args.description || meta.reason || meta.description || part.detail || part.content
  const title = args.title || args.question || meta.title || meta.question || part.label
  if (!detail || detail === title) return ''
  return compactDetail(String(detail), 200)
}

function decisionOptions(part: MessagePart): DecisionOption[] {
  const args = (part.toolArgs || {}) as Record<string, unknown>
  const meta = (part.metadata || {}) as Record<string, unknown>
  const raw = args.options || meta.options
  if (!Array.isArray(raw)) {
    return part.status === 'pending'
      ? [{ id: 'confirm', label: '确认并继续', description: '按当前方案继续执行' }]
      : []
  }
  return (raw as Array<Record<string, unknown>>)
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
    .map((item, index) => ({
      id: String(item.id || item.value || `option-${index + 1}`),
      label: String(item.label || item.title || item.id || `选项 ${index + 1}`),
      description: String(item.description || item.detail || ''),
      response: item.response ? String(item.response) : undefined,
    }))
    .filter((option) => option.label)
}

function buildResponse(part: MessagePart, option: DecisionOption): string {
  if (option.response) return option.response
  const title = decisionTitle(part).replace(/^需要确认：/, '')
  const lines = [`我选择：${option.label}`]
  if (option.description) lines.push(`原因/说明：${option.description}`)
  if (title && title !== '等待确认') lines.push(`对应决策：${title}`)
  return lines.join('\n')
}

function compactDetail(value: string, limit = 140): string {
  const oneLine = value.replace(/\s+/g, ' ').trim()
  return oneLine.length > limit ? `${oneLine.slice(0, limit)}...` : oneLine
}
</script>

<style scoped>
.floating-approval-card {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 200;
  width: min(380px, calc(100vw - 48px));
  padding: 16px 18px;
  border: 1px solid color-mix(in srgb, var(--orange) 38%, transparent);
  border-radius: var(--radius-lg, 18px);
  background: color-mix(in srgb, var(--bg, #111111) 96%, var(--orange) 4%);
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.55), 0 0 0 1px rgba(255, 145, 66, 0.12);
  display: grid;
  gap: 10px;
  font-family: var(--font-sans, sans-serif);
  backdrop-filter: blur(8px);
}

.floating-approval-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.floating-approval-icon {
  font-size: 16px;
  flex-shrink: 0;
  line-height: 1;
}

.floating-approval-title {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 650;
  color: var(--theme-main-text, var(--text, #f2efeb));
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.floating-approval-close {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--muted, #a7a29b);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: background 0.15s, color 0.15s;
}
.floating-approval-close:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--theme-main-text, var(--text, #f2efeb));
}

.floating-approval-detail {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: color-mix(in srgb, var(--theme-main-text, var(--text, #f2efeb)) 72%, transparent);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 80px;
  overflow-y: auto;
}

.floating-approval-count {
  font-size: 11.5px;
  color: var(--orange, #ff9142);
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--orange) 10%, transparent);
  justify-self: start;
}

.floating-approval-actions {
  display: flex;
  gap: 8px;
}

.floating-approval-btn {
  flex: 1;
  padding: 7px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, opacity 0.15s;
  white-space: nowrap;
}

.floating-approval-btn--approve {
  background: color-mix(in srgb, var(--green, #32d17d) 18%, transparent);
  border-color: color-mix(in srgb, var(--green, #32d17d) 32%, transparent);
  color: var(--green, #32d17d);
}
.floating-approval-btn--approve:hover {
  background: color-mix(in srgb, var(--green, #32d17d) 28%, transparent);
}

.floating-approval-btn--deny {
  background: color-mix(in srgb, var(--red, #f5555d) 18%, transparent);
  border-color: color-mix(in srgb, var(--red, #f5555d) 32%, transparent);
  color: var(--red, #f5555d);
}
.floating-approval-btn--deny:hover {
  background: color-mix(in srgb, var(--red, #f5555d) 28%, transparent);
}

.floating-approval-btn--dismiss {
  background: transparent;
  border-color: color-mix(in srgb, var(--muted, #a7a29b) 22%, transparent);
  color: var(--muted, #a7a29b);
}
.floating-approval-btn--dismiss:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--theme-main-text, var(--text, #f2efeb));
}

.floating-approval-hint {
  font-size: 10.5px;
  color: var(--faint, #726e68);
  text-align: center;
}
.floating-approval-hint kbd {
  font-family: inherit;
  font-size: 10.5px;
  padding: 1px 5px;
  border: 1px solid color-mix(in srgb, var(--faint, #726e68) 28%, transparent);
  border-radius: 4px;
  background: color-mix(in srgb, var(--faint, #726e68) 8%, transparent);
}

/* ------------------------------------------------------------------------- */
/* Transition */
/* ------------------------------------------------------------------------- */

.float-approval-enter-active {
  transition: all 0.28s cubic-bezier(0.16, 1, 0.3, 1);
}
.float-approval-leave-active {
  transition: all 0.2s cubic-bezier(0.4, 0, 1, 1);
}
.float-approval-enter-from {
  opacity: 0;
  transform: translateY(16px) scale(0.96);
}
.float-approval-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(0.97);
}
</style>