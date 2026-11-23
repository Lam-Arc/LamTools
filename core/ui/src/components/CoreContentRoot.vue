<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown, Globe } from 'lucide-vue-next'
import { openContextMenu } from './context-menu/context-menu'
import { t } from '@/i18n'
import { useOptionalWorkspace } from '@/workspace/context'
import type { WorkspaceController } from '@/workspace/types'
import type { WorkspaceLayout } from '@/workspace'
import { WORKSPACE_LAYOUTS } from '@/workspace/rootEntry'
import '@/styles/content-root.css'

const props = withDefaults(defineProps<{
  /** 已经有控制器时直接给（分屏工作区），没给就读注入的那一份（会话栏）。 */
  controller?: WorkspaceController | null
  /** bar：分屏主区的标题栏里；axis：Agent 纵向标签轴的顶端。 */
  variant?: 'bar' | 'axis'
}>(), { controller: null, variant: 'bar' })

const injected = useOptionalWorkspace()
const split = computed(() => props.controller ?? injected)
const layout = computed(() => split.value?.state.layout ?? 'agent')
const label = computed(() => WORKSPACE_LAYOUTS[layout.value])

function openMenu(event: MouseEvent) {
  const controller = split.value
  if (!controller) return
  // user:“file作为标签页级受agent布局或者browser布局管理”+(布局菜单不混入内容或已打开标签)。
  const layouts = Object.keys(WORKSPACE_LAYOUTS) as WorkspaceLayout[]
  openContextMenu({
    event,
    ariaLabel: t('切换工作区布局'),
    items: layouts.map(id => ({
      label: WORKSPACE_LAYOUTS[id],
      icon: id === 'browser' ? Globe : undefined,
      checked: layout.value === id,
      action: () => controller.setLayout(id),
    })),
  })
}
</script>

<template>
  <button
    v-if="split"
    type="button"
    class="content-root"
    :class="`content-root--${variant}`"
    data-content-root
    :data-split-main-switch="variant === 'bar' ? '' : undefined"
    :data-content-root-variant="variant"
    :title="t('切换工作区布局')"
    :aria-label="t('切换工作区布局')"
    aria-haspopup="menu"
    @click="openMenu"
  >
    <span class="content-root__label">{{ label }}</span>
    <ChevronDown class="content-root__chevron" :size="12" :stroke-width="1.8" aria-hidden="true" />
  </button>
</template>
