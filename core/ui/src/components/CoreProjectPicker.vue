<template>
  <Teleport :to="teleportTarget">
    <div class="core-project-picker-backdrop" data-project-picker-backdrop @mousedown.self="emit('cancel')">
      <section
        class="core-project-picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby="core-project-picker-title"
      >
        <header class="core-project-picker-header">
          <h2 id="core-project-picker-title">选择项目</h2>
          <p>选择一个已登记的项目继续工作。</p>
        </header>

        <div v-if="projects.length" class="core-project-picker-list" role="list">
          <button
            v-for="project in projects"
            :key="project.id"
            class="core-project-picker-item"
            type="button"
            role="listitem"
            :data-project-picker-item="project.id"
            :title="project.workRoot"
            @click="emit('select', project.id)"
          >
            <span class="core-project-picker-name">{{ project.name }}</span>
            <span class="core-project-picker-path">{{ project.workRoot }}</span>
          </button>
        </div>
        <p v-else class="core-project-picker-empty">暂无已登记项目。</p>

        <footer class="core-project-picker-actions">
          <button type="button" class="core-project-picker-cancel" data-project-picker-cancel @click="emit('cancel')">取消</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import type { CoreProject } from '../projects/types'

withDefaults(defineProps<{
  projects?: CoreProject[]
  teleportTarget?: string
}>(), {
  projects: () => [],
  teleportTarget: 'body',
})

const emit = defineEmits<{
  select: [projectId: string]
  cancel: []
}>()
</script>

<style scoped>
.core-project-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: grid;
  place-items: center;
  padding: var(--space-5);
  background: color-mix(in srgb, black 34%, transparent);
}

.core-project-picker {
  --text: var(--theme-main-text);
  width: min(520px, 100%);
  max-height: calc(100dvh - var(--space-6) - var(--space-6));
  overflow: auto;
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-background);
  color: var(--text);
  box-shadow: var(--shadow-md);
}

.core-project-picker-header {
  padding: var(--space-5) var(--space-5) 0;
}

.core-project-picker-header h2 {
  margin: 0;
  font-size: 25px;
  font-weight: 760;
  line-height: 1.2;
}

.core-project-picker-header p,
.core-project-picker-empty {
  margin: var(--space-2) 0 0;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-size: 13px;
  line-height: 1.5;
}

.core-project-picker-list {
  display: grid;
  margin-top: var(--space-4);
}

.core-project-picker-item {
  display: grid;
  gap: var(--space-1);
  width: 100%;
  min-width: 0;
  border: 0;
  padding: var(--space-3) var(--space-5);
  background: transparent;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.core-project-picker-item:hover {
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--text) var(--alpha-hover), transparent) var(--row-fade), color-mix(in srgb, var(--text) var(--alpha-hover), transparent) calc(100% - var(--row-fade)), transparent);
}

.core-project-picker-item:active {
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--text) var(--alpha-active), transparent) var(--row-fade), color-mix(in srgb, var(--text) var(--alpha-active), transparent) calc(100% - var(--row-fade)), transparent);
}

.core-project-picker-item:focus-visible,
.core-project-picker-cancel:focus-visible {
  outline: 2px solid var(--blue);
  outline-offset: -2px;
}

.core-project-picker-name,
.core-project-picker-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-project-picker-name {
  font-size: 14px;
  font-weight: 680;
}

.core-project-picker-path {
  color: color-mix(in srgb, var(--text) 52%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
}

.core-project-picker-empty {
  padding: 0 var(--space-5);
}

.core-project-picker-actions {
  display: flex;
  justify-content: flex-end;
  padding: var(--space-5);
}

.core-project-picker-cancel {
  min-height: 38px;
  border: 0;
  border-radius: var(--radius-sm);
  padding: 0 var(--space-3);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}

.core-project-picker-cancel:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-project-picker-cancel:active {
  background: color-mix(in srgb, var(--text) var(--alpha-press), transparent);
}

@media (max-width: 640px) {
  .core-project-picker-backdrop { padding: var(--space-3); }
  .core-project-picker { max-height: calc(100dvh - var(--space-6)); }
  .core-project-picker-header,
  .core-project-picker-actions { padding: var(--space-4); }
  .core-project-picker-item { padding: var(--space-3) var(--space-4); }
  .core-project-picker-empty { padding: 0 var(--space-4); }
}
</style>
