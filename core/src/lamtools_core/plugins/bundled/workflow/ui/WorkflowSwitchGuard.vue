<template>
  <!-- user:“确保视觉、功能和交互不退化”+(三种草稿选择保留原布局，键盘焦点限定在对话框内)。 -->
  <div v-if="open" class="wf-switch-guard" role="dialog" aria-modal="true" :aria-labelledby="titleId" @keydown.tab="trapDialogTab" @keydown.esc.prevent.stop="emit('choice', 'cancel')">
    <div class="wf-switch-guard-card">
      <h2 :id="titleId">{{ t('工作流有未保存修改') }}</h2>
      <p>{{ t('切换前要如何处理当前草稿？') }}</p>
      <div class="wf-switch-guard-actions">
        <button ref="cancelButton" type="button" class="text-btn" @click="emit('choice', 'cancel')">{{ t('取消') }}</button>
        <button type="button" class="text-btn" @click="emit('choice', 'discard')">{{ t('放弃修改') }}</button>
        <button type="button" class="primary-btn" @click="emit('choice', 'save')">{{ t('保存并切换') }}</button>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { t } from '../../../../../../ui/src/i18n/index'
import { trapDialogTab } from '../../../../../../ui/src/composables/trapDialogTab'
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ choice: [choice: 'save' | 'discard' | 'cancel'] }>()
const titleId = `wf-switch-guard-${useId()}`
const cancelButton = ref<HTMLButtonElement | null>(null)
let previousFocus: HTMLElement | null = null
// user:“确保视觉、功能和交互不退化”+(打开时聚焦取消，关闭时恢复原焦点，快速关闭不抢焦点)。
watch(() => props.open, async open => {
  if (open) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    if (props.open) cancelButton.value?.focus()
  } else {
    const target = previousFocus; previousFocus = null
    await nextTick()
    if (!props.open && target?.isConnected) target.focus()
  }
}, { immediate: true })
onBeforeUnmount(() => { if (props.open && previousFocus?.isConnected) previousFocus.focus() })
</script>
<style scoped>
.wf-switch-guard { position: fixed; inset: 0; z-index: var(--z-modal); display: grid; place-items: center; background: color-mix(in srgb, var(--theme-main-background) 66%, transparent); backdrop-filter: blur(2px); }
.wf-switch-guard-card { width: 360px; max-width: calc(100vw - 32px); padding: var(--space-4); border: 1px solid var(--theme-main-border); border-radius: var(--radius-md, 12px); background: var(--theme-main-background); color: var(--theme-main-text); box-shadow: var(--shadow-lg, var(--shadow-md)); }
.wf-switch-guard-card h2 { margin: 0 0 var(--space-2); font-size: 14px; }
.wf-switch-guard-card p { margin: 0; color: color-mix(in srgb, var(--theme-main-text) 68%, transparent); font-size: 12px; }
.wf-switch-guard-actions { display: flex; justify-content: flex-end; gap: var(--space-2); margin-top: var(--space-4); }
</style>
