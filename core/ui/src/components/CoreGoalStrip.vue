<script setup lang="ts">
import type { CoreGoal } from '../durable/types'

defineProps<{ goal: CoreGoal }>()
defineEmits<{ cancel: [goal: CoreGoal] }>()
</script>

<template>
  <div class="core-goal-strip" :data-status="goal.status" role="status">
    <span aria-hidden="true">◎</span>
    <span class="core-goal-objective">{{ goal.objective }}</span>
    <span class="core-goal-status">{{ goal.status === 'blocked' ? '已暂停' : goal.status === 'pending' ? '待开始' : '进行中' }}</span>
    <button type="button" @click="$emit('cancel', goal)">取消</button>
  </div>
</template>

<style scoped>
.core-goal-strip { display: flex; align-items: center; gap: 8px; width: min(680px, calc(100vw - 32px)); min-width: 0; margin: 0 auto 7px; padding: 7px 10px; color: var(--text); background: color-mix(in srgb, var(--blue) 9%, var(--panel-2)); border-radius: var(--radius-sm); font-size: 13px; }
.core-goal-strip[data-status='blocked'] { background: color-mix(in srgb, var(--orange) 10%, var(--panel-2)); }
.core-goal-objective { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.core-goal-status { margin-left: auto; color: var(--muted); white-space: nowrap; }
button { border: 0; padding: 2px 4px; color: var(--muted); background: transparent; cursor: pointer; }
button:hover, button:focus-visible { color: var(--text); }
button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
@media (max-width: 700px) { button { min-width: 44px; min-height: 44px; } }
</style>
