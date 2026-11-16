<template>
  <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(记忆与方案的命名表单共用结构，保留输入、忙碌和错误状态)。 -->
  <div ref="backdropEl" class="dialog-dimmer" @click.self="onBackdropClick">
    <div ref="dialogEl" v-bind="$attrs" class="dialog-card" role="dialog" aria-modal="true" :aria-label="title" @keydown.tab="trapDialogTab" @keydown.esc.prevent.stop="$emit('cancel')">
      <div class="dialog-body">
        <h3 class="dialog-title">{{ title }}</h3>
        <label class="dialog-field">
          <span>{{ fieldLabel }}</span>
          <input ref="inputEl" v-bind="inputAttrs" type="text" :value="modelValue" :placeholder="placeholder" @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)" @keydown.enter.prevent="submit" />
        </label>
        <p v-if="error" class="dialog-error" role="alert">{{ error }}</p>
      </div>
      <div class="dialog-actions">
        <button class="library-button" type="button" @click="$emit('cancel')">{{ t('取消') }}</button>
        <button v-bind="submitAttrs" class="library-button library-button--primary" type="button" :disabled="busy || !modelValue.trim()" @click="submit">{{ busy ? t('处理中…') : submitLabel }}</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { t } from '@/i18n/index.ts'
import { trapDialogTab } from '@/composables/trapDialogTab.ts'
import { useOutsidePointerDismiss } from '@/composables/useOutsidePointerDismiss.ts'
defineOptions({ inheritAttrs: false })
const props = defineProps<{ title: string; fieldLabel: string; modelValue: string; submitLabel: string; placeholder?: string; error?: string; busy?: boolean; inputAttrs?: Record<string, string>; submitAttrs?: Record<string, string> }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; submit: []; cancel: [] }>()
const inputEl = ref<HTMLInputElement | null>(null)
const backdropEl = ref<HTMLElement | null>(null)
const dialogEl = ref<HTMLElement | null>(null)
// user:“确保视觉、功能和交互不退化”+(只在完整点击遮罩时关闭，卡内拖到遮罩不丢失编辑内容)。
useOutsidePointerDismiss({ overlay: backdropEl, card: dialogEl, onDismiss: () => emit('cancel') })
function onBackdropClick(event: MouseEvent) { if (event.detail === 0) emit('cancel') }
// user:“确保视觉、功能和交互不退化”+(打开表单时聚焦名称输入，忙碌或空值时不能重复提交)。
// user:“确保视觉、功能和交互不退化”+(从任意对话框操作键按 Escape 可关闭，关闭后回到打开位置)。
let previousFocus: HTMLElement | null = null
onMounted(() => {
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  inputEl.value?.focus()
})
onBeforeUnmount(() => { if (previousFocus?.isConnected) previousFocus.focus() })
function submit() { if (!props.busy && props.modelValue.trim()) emit('submit') }
</script>
