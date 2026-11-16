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
          class="right-sidebar-checklist__indicator sunday-task-indicator"
          :class="{ 'right-sidebar-checklist__indicator--running sunday-task-indicator--running sunday-spin sunday-spin--task': step.status === 'running' }"
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
    <p v-if="!stepGroups.length" class="right-sidebar-checklist__empty">{{ t("当前没有 checklist") }}</p>
  </div>
</template>

<script setup lang="ts">
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(侧栏与计划卡共享步骤状态样式)。
import '@/styles/sunday-task-indicator.css'
import { runtimeStepStatusLabel as statusLabel } from '@/helpers/runtimeStepStatus.ts'
import { t } from '@/i18n/index.ts'

import type { CoreRuntimeStepGroup } from '@/types.ts'

withDefaults(defineProps<{
  stepGroups?: CoreRuntimeStepGroup[]
}>(), {
  stepGroups: () => [],
})

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

</style>
