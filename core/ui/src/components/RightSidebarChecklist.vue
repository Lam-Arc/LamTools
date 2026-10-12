<template>
  <div class="right-sidebar-checklist">
    <section
      v-for="group in stepGroups"
      :key="group.id"
      class="right-sidebar-checklist__group"
      :aria-label="group.label"
    >
      <div
        v-for="step in group.steps"
        :key="step.id"
        class="right-sidebar-checklist__step"
        :class="`is-${step.status}`"
        :data-status="step.status"
      >
        <span
          class="right-sidebar-checklist__indicator"
          :class="{ 'right-sidebar-checklist__indicator--running': step.status === 'running' }"
          aria-hidden="true"
        >{{ step.status === 'completed' ? '✓' : step.status === 'failed' ? '!' : '' }}</span>
        <div class="right-sidebar-checklist__step-body">
          <span class="right-sidebar-checklist__step-title">{{ step.title }}</span>
          <ul v-if="step.deliverables?.length" class="right-sidebar-checklist__deliverables">
            <li v-for="deliverable in step.deliverables" :key="deliverable">{{ deliverable }}</li>
          </ul>
        </div>
        <span class="right-sidebar-checklist__step-status">{{ statusLabel(step.status) }}</span>
      </div>
    </section>
    <p v-if="!stepGroups.length" class="right-sidebar-checklist__empty">当前没有 checklist</p>
  </div>
</template>

<script setup lang="ts">
import type { CoreRuntimeStepGroup, CoreRuntimeStepStatus } from '../types'

withDefaults(defineProps<{
  stepGroups?: CoreRuntimeStepGroup[]
}>(), {
  stepGroups: () => [],
})

function statusLabel(status: CoreRuntimeStepStatus): string {
  return ({
    pending: '待处理',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    skipped: '已跳过',
  } as Record<CoreRuntimeStepStatus, string>)[status]
}
</script>

<style scoped>
.right-sidebar-checklist { --text: var(--theme-backdrop-text); display: grid; gap: var(--space-3); color: var(--text); font-size: 12px; }

.right-sidebar-checklist__group { display: grid; gap: var(--space-1); }

.right-sidebar-checklist__step {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-1) 0;
  color: color-mix(in srgb, var(--text) 72%, transparent);
}

.right-sidebar-checklist__step.is-running { color: color-mix(in srgb, var(--green) 78%, var(--text) 22%); }
.right-sidebar-checklist__step.is-failed { color: color-mix(in srgb, var(--red) 78%, var(--text) 22%); }

.right-sidebar-checklist__indicator {
  display: inline-grid;
  flex: 0 0 16px;
  place-items: center;
  width: 16px;
  height: 16px;
  margin-top: 1px;
  border: 1px solid color-mix(in srgb, var(--text) 25%, transparent);
  border-radius: 50%;
  color: var(--green);
  font-size: 11px;
  line-height: 1;
}
.right-sidebar-checklist__indicator--running {
  border-color: var(--green);
  animation: right-sidebar-checklist-spin 1.2s linear infinite;
}
.right-sidebar-checklist__step.is-failed .right-sidebar-checklist__indicator {
  border-color: var(--red);
  color: var(--red);
}

.right-sidebar-checklist__step-body {
  display: grid;
  flex: 1;
  gap: var(--space-1);
  min-width: 0;
}

.right-sidebar-checklist__step-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.right-sidebar-checklist__deliverables {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-size: 11px;
  line-height: 1.35;
  list-style: none;
}
.right-sidebar-checklist__deliverables li {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.right-sidebar-checklist__deliverables li::before {
  content: '•';
  margin-right: var(--space-1);
  color: color-mix(in srgb, var(--green) 72%, var(--text) 28%);
}

.right-sidebar-checklist__step-status {
  flex-shrink: 0;
  color: color-mix(in srgb, var(--text) 52%, transparent);
  font-size: 11px;
  white-space: nowrap;
}
.right-sidebar-checklist__step.is-running .right-sidebar-checklist__step-status {
  color: color-mix(in srgb, var(--green) 76%, var(--text) 24%);
}
.right-sidebar-checklist__step.is-failed .right-sidebar-checklist__step-status {
  color: color-mix(in srgb, var(--red) 76%, var(--text) 24%);
}

.right-sidebar-checklist__empty {
  margin: 0;
  color: color-mix(in srgb, var(--text) 52%, transparent);
  font-size: 12px;
}

@keyframes right-sidebar-checklist-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .right-sidebar-checklist__indicator--running { animation: none; }
}
</style>
