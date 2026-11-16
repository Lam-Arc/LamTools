<template>
  <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(资料库确认框共享结构，保留完整警告、原有样式和取消行为)。 -->
  <Transition name="library-dialog">
    <div v-if="open" ref="backdropEl" class="dialog-dimmer" @click.self="onBackdropClick" @keydown.esc.prevent.stop="$emit('cancel')">
      <div ref="dialogEl" v-bind="$attrs" class="dialog-card" role="dialog" aria-modal="true" :aria-label="ariaLabel || title" @keydown.tab="trapDialogTab">
        <div class="dialog-body">
          <h3 class="dialog-title">{{ title }}</h3>
          <p class="dialog-text"><slot /></p>
        </div>
        <div class="dialog-actions">
          <button ref="cancelButton" class="library-button" type="button" @click="$emit('cancel')">{{ cancelLabel || t('取消') }}</button>
          <button v-bind="confirmAttrs" class="library-button library-button--danger" type="button" @click="$emit('confirm')">{{ confirmLabel }}</button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { t } from '@/i18n/index.ts'
import { trapDialogTab } from '@/composables/trapDialogTab.ts'
import { useOutsidePointerDismiss } from '@/composables/useOutsidePointerDismiss.ts'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ open: boolean; title: string; ariaLabel?: string; confirmLabel: string; cancelLabel?: string; confirmAttrs?: Record<string, string> }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const cancelButton = ref<HTMLButtonElement | null>(null)
const backdropEl = ref<HTMLElement | null>(null)
const dialogEl = ref<HTMLElement | null>(null)
// user:“确保视觉、功能和交互不退化”+(只在完整点击遮罩时取消，卡内拖出不会误关闭)。
useOutsidePointerDismiss({ overlay: backdropEl, card: dialogEl, isActive: () => props.open, onDismiss: () => emit('cancel') })
function onBackdropClick(event: MouseEvent) { if (event.detail === 0) emit('cancel') }
let previousFocus: HTMLElement | null = null
// user:“确保视觉、功能和交互不退化”+(打开时聚焦取消，关闭后返回原位置；快速关闭时不抢焦点)。
watch(() => props.open, async open => {
  if (open) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    if (props.open) cancelButton.value?.focus()
  } else {
    previousFocus?.focus()
    previousFocus = null
  }
}, { immediate: true })
onBeforeUnmount(() => { previousFocus?.focus(); previousFocus = null })
</script>
