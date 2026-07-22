<script setup lang="ts">
import type { CoreGoal } from '../durable/types'

defineProps<{ goal: CoreGoal }>()
defineEmits<{ cancel: [goal: CoreGoal] }>()
</script>

<template>
  <div class="core-goal-strip" :data-status="goal.status" role="status">
    <span aria-hidden="true">◎</span>
    <span class="core-goal-objective">{{ goal.objective }}</span>
    <span class="core-goal-status">{{ goal.status === 'blocked' ? '已暂停' : '进行中' }}</span>
    <button type="button" @click="$emit('cancel', goal)">取消</button>
  </div>
</template>

<style scoped>
/* ===== Goal status strip — lives inside ComposerBar #preamble ===== */

.core-goal-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
  z-index: 2;
  width: 100%;                              /* match composer width at every breakpoint */
  min-width: 0;
  padding: 6px 16px;                        /* horizontal: same as composer textarea */
  color: var(--text);
  font-size: 13px;
  line-height: 1.4;
}

/* icon */
.core-goal-strip > [aria-hidden="true"] {
  flex-shrink: 0;
  font-size: 12px;
  opacity: 0.55;
}

/* objective — flexible, truncates on overflow */
.core-goal-objective {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* status label — fixed, pushed to far right */
.core-goal-status {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
  margin-left: auto;
}

/* cancel button */
button {
  flex-shrink: 0;
  padding: 2px 8px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 16%, transparent);
  border-radius: 4px;
  background: transparent;
  color: var(--muted);
  font-size: 11px;
  cursor: pointer;
  line-height: 1.4;
  transition: background 120ms, color 120ms, border-color 120ms;
}
button:hover,
button:focus-visible {
  background: color-mix(in srgb, var(--theme-composer-text) 10%, transparent);
  color: var(--text);
  border-color: color-mix(in srgb, var(--theme-composer-text) 28%, transparent);
}
button:focus-visible {
  outline: 2px solid var(--blue);
  outline-offset: 2px;
}

/* ===== Responsive ===== */

/* narrow: hide status label, keep objective + cancel */
@media (max-width: 520px) {
  .core-goal-status {
    display: none;
  }
}

/* very narrow: tighten everything */
@media (max-width: 380px) {
  .core-goal-strip {
    padding: 5px 12px;
    gap: 6px;
    font-size: 12px;
  }
  button {
    padding: 2px 6px;
    font-size: 10px;
  }
}

/* touch: larger tap target */
@media (max-width: 700px) {
  button {
    min-width: 36px;
    min-height: 36px;
  }
}
</style>
