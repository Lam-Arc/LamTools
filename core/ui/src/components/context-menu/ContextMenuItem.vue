<template>
  <button
    ref="buttonRef"
    type="button"
    class="context-menu-item"
    :class="{ 'is-focused': focused, 'is-destructive': entry.destructive }"
    role="menuitem"
    :tabindex="tabindex"
    :disabled="entry.disabled"
    :aria-disabled="entry.disabled ? 'true' : undefined"
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
    <span v-if="entry.shortcut" class="context-menu-item-shortcut">{{ entry.shortcut }}</span>
  </button>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { ContextMenuAction } from './types'

defineProps<{
  entry: ContextMenuAction
  focused: boolean
  tabindex: number
  dataIndex: number
}>()

const buttonRef = ref<HTMLButtonElement | null>(null)

const emit = defineEmits<{
  mounted: [element: HTMLButtonElement]
  activate: []
  'pointer-enter': []
  focus: []
  keydown: [event: KeyboardEvent]
}>()

onMounted(() => {
  if (buttonRef.value) emit('mounted', buttonRef.value)
})

defineExpose({
  element: buttonRef,
})
</script>
