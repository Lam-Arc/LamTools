<script setup lang="ts">
import { computed, provide } from 'vue'
import type { SplitTab } from '@/workspace/types'
import { WORKSPACE_AREA_RECT, WORKSPACE_CONTENT_RECT, type WorkspaceContentTarget } from './workspaceInjection'

const props = defineProps<{
  tab: SplitTab
  pane: string
  visible: boolean
  host?: WorkspaceContentTarget
}>()

// user:“快速精准高效的解决”+(内容按标签保活，移动时只换绘制位置和原生网页的矩形来源)。
provide(WORKSPACE_AREA_RECT, id => id === props.tab.id ? props.host?.rects() ?? null : null)
provide(WORKSPACE_CONTENT_RECT, computed(() => props.host?.rects().contentRect ?? { x: 0, y: 0, width: 0, height: 0 }))
const shown = computed(() => Boolean(props.host && props.visible))
</script>

<template>
  <Teleport :to="host?.element" :disabled="!host">
    <div v-show="shown" class="ws2-area__pane-slot">
      <slot :tab="tab" :pane="pane" :visible="shown" />
    </div>
  </Teleport>
</template>
