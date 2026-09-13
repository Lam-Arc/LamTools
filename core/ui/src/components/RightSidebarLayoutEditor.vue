<template>
  <section class="right-sidebar-layout-editor" aria-label="编辑右侧面板布局">
    <div class="right-sidebar-layout-editor-head">
      <span>显示模块</span>
      <button type="button" @click="$emit('reset')">恢复默认</button>
    </div>
    <label v-for="module in modules" :key="module.id" class="right-sidebar-layout-editor-item">
      <input
        type="checkbox"
        :checked="layout.visible[module.id] !== false"
        @change="$emit('toggle-visible', module.id, ($event.target as HTMLInputElement).checked)"
      />
      <component :is="module.icon || Circle" :size="14" :stroke-width="1.8" aria-hidden="true" />
      <span>{{ module.title }}</span>
    </label>
  </section>
</template>

<script setup lang="ts">
import { Circle } from 'lucide-vue-next'
import type { RightSidebarLayoutState, RightSidebarModuleDefinition } from '../right-sidebar/types'

defineProps<{
  modules: RightSidebarModuleDefinition[]
  layout: RightSidebarLayoutState
}>()

defineEmits<{
  reset: []
  'toggle-visible': [moduleId: string, visible: boolean]
}>()
</script>

<style scoped>
.right-sidebar-layout-editor { display: grid; gap: var(--space-1); padding: var(--space-2) var(--space-3); border-bottom: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent); background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); }
.right-sidebar-layout-editor-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); min-height: 28px; color: color-mix(in srgb, var(--theme-backdrop-text) 62%, transparent); font-size: 11px; }
.right-sidebar-layout-editor-head button { min-height: 28px; padding: 0 var(--space-2); border: 1px solid color-mix(in srgb, var(--theme-control-text) 14%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); font-size: 11px; }
.right-sidebar-layout-editor-head button:hover { background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), var(--theme-control-background)); }
.right-sidebar-layout-editor-item { display: flex; align-items: center; gap: var(--space-2); min-height: 32px; color: var(--theme-backdrop-text); font-size: 12px; cursor: pointer; }
.right-sidebar-layout-editor-item input { width: 14px; height: 14px; margin: 0; padding: 0; accent-color: var(--green); }
.right-sidebar-layout-editor-item svg { color: color-mix(in srgb, var(--theme-backdrop-text) 58%, transparent); }
@media (max-width: 640px) { .right-sidebar-layout-editor-item { min-height: 44px; } .right-sidebar-layout-editor-head button { min-height: 44px; } }
</style>
