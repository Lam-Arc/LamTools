<template>
  <div class="right-sidebar-runtime-status" :data-state="normalizedState" role="status" aria-live="polite">
    <span class="right-sidebar-runtime-status-icon" aria-hidden="true">
      <LoaderCircle v-if="normalizedState === 'running'" :size="14" :stroke-width="1.8" class="spinning" />
      <Clock3 v-else-if="normalizedState === 'waiting'" :size="14" :stroke-width="1.8" />
      <TriangleAlert v-else-if="normalizedState === 'error'" :size="14" :stroke-width="1.8" />
      <CircleCheck v-else-if="normalizedState === 'completed'" :size="14" :stroke-width="1.8" />
      <Circle v-else :size="12" :stroke-width="1.8" />
    </span>
    <span class="right-sidebar-runtime-status-label">{{ stateLabel }}</span>
    <span v-if="modeLabel" class="right-sidebar-runtime-status-mode">{{ modeLabel }}</span>
    <span v-if="detail" class="right-sidebar-runtime-status-detail">{{ detail }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Circle, CircleCheck, Clock3, LoaderCircle, TriangleAlert } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  status?: string | null
  modeLabel?: string
  detail?: string
}>(), {
  status: 'idle',
  modeLabel: '',
  detail: '',
})

type RuntimeState = 'idle' | 'running' | 'waiting' | 'completed' | 'error'
const normalizedState = computed<RuntimeState>(() => {
  const value = String(props.status || '').toLowerCase()
  if (value === 'running' || value === 'active' || value === 'streaming') return 'running'
  if (value === 'waiting' || value === 'queued' || value === 'pending') return 'waiting'
  if (value === 'error' || value === 'failed' || value === 'failure') return 'error'
  if (value === 'completed' || value === 'complete' || value === 'done' || value === 'success') return 'completed'
  return 'idle'
})
const stateLabel = computed(() => {
  switch (normalizedState.value) {
    case 'running': return '运行中'
    case 'waiting': return '等待中'
    case 'completed': return '已完成'
    case 'error': return '运行失败'
    default: return '空闲'
  }
})
</script>

<style scoped>
.right-sidebar-runtime-status { display: flex; align-items: center; gap: var(--space-2); min-width: 0; min-height: 24px; color: color-mix(in srgb, var(--theme-backdrop-text) 72%, transparent); font-size: 12px; }
.right-sidebar-runtime-status-icon { display: inline-flex; flex: 0 0 auto; color: color-mix(in srgb, var(--theme-backdrop-text) 64%, transparent); }
.right-sidebar-runtime-status-label { flex: 0 0 auto; font-weight: 650; }
.right-sidebar-runtime-status-mode { min-width: 0; overflow: hidden; color: color-mix(in srgb, var(--theme-backdrop-text) 52%, transparent); text-overflow: ellipsis; white-space: nowrap; }
.right-sidebar-runtime-status-detail { min-width: 0; margin-left: auto; overflow: hidden; color: color-mix(in srgb, var(--theme-backdrop-text) 48%, transparent); text-overflow: ellipsis; white-space: nowrap; }
.right-sidebar-runtime-status[data-state="running"] .right-sidebar-runtime-status-icon { color: var(--blue); }
.right-sidebar-runtime-status[data-state="waiting"] .right-sidebar-runtime-status-icon { color: var(--orange); }
.right-sidebar-runtime-status[data-state="error"] .right-sidebar-runtime-status-icon { color: var(--red); }
.right-sidebar-runtime-status[data-state="completed"] .right-sidebar-runtime-status-icon { color: var(--theme-backdrop-text); }
.spinning { animation: right-sidebar-runtime-spin .9s linear infinite; }
@keyframes right-sidebar-runtime-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinning { animation: none; } }
</style>
