<template>
  <button
    ref="buttonRef"
    type="button"
    class="context-menu-item context-menu-submenu-trigger"
    :class="{ 'is-focused': focused }"
    role="menuitem"
    aria-haspopup="menu"
    :aria-expanded="expanded ? 'true' : 'false'"
    :tabindex="tabindex"
    :disabled="entry.disabled || entry.children.length === 0"
    :aria-disabled="entry.disabled || entry.children.length === 0 ? 'true' : undefined"
    :data-context-menu-index="dataIndex"
    v-bind="entry.attributes"
    @click="$emit('activate')"
    @pointerenter="$emit('pointer-enter')"
    @focus="$emit('focus')"
    @keydown="$emit('keydown', $event)"
  >
    <span class="context-menu-item-main">
      <component
        :is="entry.icon"
        v-if="entry.icon"
        class="context-menu-item-icon"
        :size="16"
        :stroke-width="1.8"
        aria-hidden="true"
      />
      <span>{{ entry.label }}</span>
    </span>
    <ChevronRight class="context-menu-submenu-chevron" :size="15" :stroke-width="1.8" aria-hidden="true" />
  </button>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ChevronRight } from 'lucide-vue-next'
import type { ContextMenuSubmenu as ContextMenuSubmenuEntry } from './types'

defineProps<{
  entry: ContextMenuSubmenuEntry
  focused: boolean
  expanded: boolean
  tabindex: number
  dataIndex: number
}>()

const emit = defineEmits<{
  mounted: [element: HTMLButtonElement]
  activate: []
  'pointer-enter': []
  focus: []
  keydown: [event: KeyboardEvent]
}>()

const buttonRef = ref<HTMLButtonElement | null>(null)

onMounted(() => {
  if (buttonRef.value) emit('mounted', buttonRef.value)
})

defineExpose({
  element: buttonRef,
})
</script>
