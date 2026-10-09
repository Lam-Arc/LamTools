<template>
  <div class="composer-root" :class="'composer-root--' + variant">
    <form
      class="floating-composer"
      :class="[{ dragover: dragOver }, 'composer-bar--' + variant]"
      @submit.prevent="$emit('submit')"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop.prevent="$emit('drop', $event); dragOver = false"
    >
      <slot name="popover" />
      <slot name="preamble" />
      <div class="composer-main-card">
        <slot name="status" />
        <slot name="textarea">
          <textarea
            :value="modelValue"
            :placeholder="placeholder"
            :aria-label="textareaAriaLabel || placeholder"
            :disabled="disabled"
            rows="1"
            @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
            @keydown.enter.exact="onEnterKey"
          />
        </slot>
        <div class="composer-bottom">
          <div class="tool-row">
            <slot name="attach-button" />
            <slot name="tools" />
          </div>
          <slot name="action">
            <CoreSendStopButton
              :action-mode="actionMode"
              :disabled="actionMode === 'send' && (disabled || !(modelValue || '').trim())"
              :send-label="sendLabel"
              :stop-label="stopLabel"
              :send-title="sendTitle"
              :stop-title="stopTitle"
            />
          </slot>
        </div>
      </div>
      <div class="drop-hint">拖拽到这里上传</div>
    </form>
    <slot name="extras" />
  </div>
</template>

<script setup lang="ts">
/**
 * ComposerBar — floating composer bar (composer layer in the four-layer system)
 *
 * Renders a floating or embedded textarea with toolbar and send button.
 * Drag-and-drop support via slots and events.
 */
import { ref } from 'vue'
import CoreSendStopButton from './CoreSendStopButton.vue'

const props = withDefaults(defineProps<{
  modelValue?: string
  placeholder?: string
  textareaAriaLabel?: string
  disabled?: boolean
  actionMode?: 'send' | 'stop'
  variant?: 'floating' | 'embedded'
  sendLabel?: string
  stopLabel?: string
  sendTitle?: string
  stopTitle?: string
}>(), {
  modelValue: '',
  placeholder: '输入内容...',
  textareaAriaLabel: '',
  actionMode: 'send',
  variant: 'floating',
  sendLabel: 'send',
  stopLabel: 'stop',
  sendTitle: '发送',
  stopTitle: '停止运行',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  submit: []
  drop: [event: DragEvent]
}>()

const dragOver = ref(false)
// IME guard: the composition-confirm Enter must not submit the message
// (audit 19 S3 — the default textarea previously emitted submit on any
// plain Enter, which misfired for CJK users). Enter only sends: an empty
// composer must not reach the host, whose submit handler reads it as stop.
function onEnterKey(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  const value = (event.target as HTMLTextAreaElement | null)?.value || ''
  if (!value.trim()) return
  emit('submit')
}
</script>

<style scoped>
.composer-root--embedded {
  min-width: 0;
  width: 100%;
}

.composer-root .floating-composer.composer-bar--embedded {
  position: relative;
  inset: auto;
  left: auto;
  bottom: auto;
  width: 100%;
  max-width: none;
  transform: none;
  z-index: auto;
  border-radius: var(--radius);
  box-shadow: none;
  transition: border-color 160ms cubic-bezier(.25, 1, .5, 1);
}

@media (prefers-reduced-motion: reduce) {
  .composer-root .floating-composer.composer-bar--embedded {
    transition: none;
  }
}
</style>
