<template>
  <section class="runtime-widget core-sub-agent-panel" :aria-labelledby="titleId">
    <div class="runtime-widget-head core-sub-agent-panel__head">
      <div>
        <h3 :id="titleId">{{ title }}</h3>
        <p>{{ summaryText }}</p>
      </div>
    </div>

    <div :id="listId" class="core-sub-agent-panel__list">
      <div
        v-if="errorText"
        class="core-sub-agent-panel__notice is-error"
        role="alert"
      >
        <span>{{ errorText }}</span>
        <button type="button" @click="$emit('retry')">重试</button>
      </div>
      <p v-else-if="loading && runs.length === 0" class="core-sub-agent-panel__notice" role="status">
        正在读取 Sub Agent 记录...
      </p>

      <button
        v-for="run in visibleRuns"
        :key="run.subSessionId"
        type="button"
        class="core-sub-agent-panel__row"
        :class="{ 'is-active': activeSubAgentId === run.subSessionId }"
        :data-sub-agent-id="run.subSessionId"
        aria-haspopup="dialog"
        :aria-controls="dialogId || undefined"
        :aria-expanded="activeSubAgentId === run.subSessionId"
        :aria-describedby="tooltipRun?.subSessionId === run.subSessionId ? tooltipId : undefined"
        @mouseenter="showTooltip(run, $event)"
        @mouseleave="hideTooltip"
        @focus="showTooltip(run, $event)"
        @blur="hideTooltip"
        @click="openRun(run)"
      >
        <span class="core-sub-agent-panel__dot" :class="'is-' + run.status" aria-hidden="true" />
        <span class="core-sub-agent-panel__name">{{ run.name }}</span>
        <span class="core-sub-agent-panel__status">{{ statusLabel(run.status) }}</span>
      </button>

      <button
        v-if="overflowCount > 0"
        type="button"
        class="core-sub-agent-panel__more"
        :aria-expanded="expanded"
        :aria-controls="listId"
        @click="expanded = !expanded"
      >
        <span aria-hidden="true">{{ expanded ? '−' : '…' }}</span>
        <span>{{ expanded ? '收起' : '查看其余 ' + overflowCount + ' 个' }}</span>
      </button>

      <p v-if="runs.length === 0 && !loading && !errorText" class="core-sub-agent-panel__empty">{{ emptyText }}</p>
    </div>

    <Teleport to="body">
      <Transition name="sub-agent-tooltip">
        <div
          v-if="tooltipRun"
          :id="tooltipId"
          class="core-sub-agent-tooltip"
          role="tooltip"
          :style="tooltipStyle"
        >
          <span>首次任务</span>
          <p>{{ tooltipRun.task || '未记录任务内容。' }}</p>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import type { CoreSubAgentRun, MessagePartStatus } from '../types'

const props = withDefaults(defineProps<{
  runs: readonly CoreSubAgentRun[]
  limit?: number
  title?: string
  emptyText?: string
  activeSubAgentId?: string
  dialogId?: string
  loading?: boolean
  errorText?: string
}>(), {
  limit: 4,
  title: 'Sub Agents',
  emptyText: '尚未启动 Sub Agent',
  activeSubAgentId: '',
  dialogId: '',
  loading: false,
  errorText: '',
})

const emit = defineEmits<{
  open: [subSessionId: string]
  retry: []
}>()

const instanceId = useId().replace(/[^a-zA-Z0-9_-]/g, '')
const titleId = 'core-sub-agent-title-' + instanceId
const listId = 'core-sub-agent-list-' + instanceId
const tooltipId = 'core-sub-agent-tooltip-' + instanceId
const expanded = ref(false)
const tooltipRun = ref<CoreSubAgentRun | null>(null)
const tooltipTrigger = ref<HTMLElement | null>(null)
const tooltipStyle = ref<Record<string, string>>({})

const safeLimit = computed(() => Math.min(4, Math.max(1, Math.floor(props.limit))))
const overflowCount = computed(() => Math.max(0, props.runs.length - safeLimit.value))
const visibleRuns = computed(() => expanded.value ? props.runs : props.runs.slice(0, safeLimit.value))
const summaryText = computed(() => {
  if (props.runs.length > 0) return props.runs.length + ' 个记录'
  if (props.loading) return '读取中'
  if (props.errorText) return '读取失败'
  return props.emptyText
})

watch(
  () => props.runs.map(run => run.subSessionId).sort().join('\u0000'),
  () => {
    expanded.value = false
    hideTooltip()
  },
)

function openRun(run: CoreSubAgentRun) {
  hideTooltip()
  emit('open', run.subSessionId)
}

function showTooltip(run: CoreSubAgentRun, event: Event) {
  const trigger = event.currentTarget
  if (!(trigger instanceof HTMLElement)) return
  tooltipRun.value = run
  tooltipTrigger.value = trigger
  updateTooltipPosition()
}

function hideTooltip() {
  tooltipRun.value = null
  tooltipTrigger.value = null
}

function updateTooltipPosition() {
  const trigger = tooltipTrigger.value
  if (!trigger || !tooltipRun.value) return
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(320, Math.max(220, window.innerWidth - 24))
  let left = rect.left - width - 10
  if (left < 12) left = Math.min(window.innerWidth - width - 12, rect.right + 10)
  const top = Math.max(12, Math.min(window.innerHeight - 156, rect.top - 8))
  const styles = getComputedStyle(trigger)
  tooltipStyle.value = {
    left: Math.round(left) + 'px',
    top: Math.round(top) + 'px',
    width: Math.round(width) + 'px',
    '--sub-agent-tooltip-bg': styles.getPropertyValue('--theme-backdrop-background') || '#202020',
    '--sub-agent-tooltip-text': styles.getPropertyValue('--theme-backdrop-text') || '#f2efeb',
  }
}

function statusLabel(status: MessagePartStatus): string {
  if (status === 'running') return '运行中'
  if (status === 'pending') return '等待中'
  if (status === 'error') return '失败'
  return '已完成'
}

onMounted(() => {
  window.addEventListener('resize', updateTooltipPosition)
  window.addEventListener('scroll', updateTooltipPosition, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateTooltipPosition)
  window.removeEventListener('scroll', updateTooltipPosition, true)
})
</script>

<style scoped>
.core-sub-agent-panel {
  color: var(--theme-backdrop-text, var(--text));
}

.core-sub-agent-panel__head p {
  font-variant-numeric: tabular-nums;
}

.core-sub-agent-panel__list {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.core-sub-agent-panel__notice {
  min-height: 2.25rem;
  margin: 0;
  padding: .5rem;
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 62%, transparent);
  font-size: .75rem;
  line-height: 1.45;
}

.core-sub-agent-panel__notice.is-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
  color: color-mix(in srgb, var(--red, #ef6b63) 78%, var(--theme-backdrop-text, currentColor));
}

.core-sub-agent-panel__notice button {
  min-height: 2rem;
  border: 0;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 8%, transparent);
  color: inherit;
  padding: 0 .625rem;
  font: inherit;
  cursor: pointer;
}

.core-sub-agent-panel__notice button:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 12%, transparent);
}

.core-sub-agent-panel__row {
  width: 100%;
  min-width: 0;
  min-height: 2.25rem;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: .5rem;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  padding: 0 .5rem;
  text-align: left;
  cursor: pointer;
}

.core-sub-agent-panel__row:hover,
.core-sub-agent-panel__row.is-active {
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 7%, transparent);
}

.core-sub-agent-panel__row:active {
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 10%, transparent);
}

.core-sub-agent-panel__row:focus-visible,
.core-sub-agent-panel__more:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--green, #5fca87) 62%, white 8%);
  outline-offset: 2px;
}

.core-sub-agent-panel__dot {
  width: .5rem;
  height: .5rem;
  border-radius: 50%;
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 38%, transparent);
}

.core-sub-agent-panel__dot.is-running {
  background: var(--green, #5fca87);
}

.core-sub-agent-panel__dot.is-pending {
  background: var(--orange, #e9a23b);
}

.core-sub-agent-panel__dot.is-error {
  background: var(--red, #ef6b63);
}

.core-sub-agent-panel__name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: .8125rem;
  font-weight: 650;
  line-height: 1.35;
}

.core-sub-agent-panel__status {
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 58%, transparent);
  font-size: .6875rem;
  line-height: 1.35;
  white-space: nowrap;
}

.core-sub-agent-panel__more {
  width: 100%;
  min-height: 2rem;
  display: grid;
  grid-template-columns: 1rem minmax(0, 1fr);
  align-items: center;
  gap: .5rem;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 62%, transparent);
  padding: 0 .5rem;
  font: inherit;
  font-size: .75rem;
  text-align: left;
  cursor: pointer;
}

.core-sub-agent-panel__more:hover {
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 6%, transparent);
  color: var(--theme-backdrop-text, currentColor);
}

.core-sub-agent-panel__more span:first-child {
  color: var(--theme-backdrop-text, currentColor);
  font-family: var(--font-mono, monospace);
  font-weight: 800;
  text-align: center;
}

.core-sub-agent-panel__empty {
  margin: 0;
  padding: .5rem;
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 56%, transparent);
  font-size: .75rem;
  line-height: 1.5;
}

.core-sub-agent-tooltip {
  position: fixed;
  z-index: var(--z-popover, 60);
  max-height: 9rem;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--sub-agent-tooltip-text) 13%, transparent);
  border-radius: var(--radius);
  background: var(--sub-agent-tooltip-bg);
  color: var(--sub-agent-tooltip-text);
  box-shadow: var(--shadow-sm);
  padding: .75rem .875rem;
  pointer-events: none;
}

.core-sub-agent-tooltip span {
  display: block;
  color: color-mix(in srgb, var(--sub-agent-tooltip-text) 58%, transparent);
  font-size: .6875rem;
  font-weight: 650;
  line-height: 1.35;
}

.core-sub-agent-tooltip p {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  overflow: hidden;
  margin: .375rem 0 0;
  font-size: .8125rem;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.sub-agent-tooltip-enter-active,
.sub-agent-tooltip-leave-active {
  transition: opacity 160ms cubic-bezier(.25, 1, .5, 1), transform 160ms cubic-bezier(.25, 1, .5, 1);
}

.sub-agent-tooltip-enter-from,
.sub-agent-tooltip-leave-to {
  opacity: 0;
  transform: translateX(4px);
}

@media (pointer: coarse) {
  .core-sub-agent-panel__row,
  .core-sub-agent-panel__more {
    min-height: 2.75rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .sub-agent-tooltip-enter-active,
  .sub-agent-tooltip-leave-active {
    transition: none;
  }
}
</style>
