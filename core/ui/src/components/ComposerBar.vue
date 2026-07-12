<template>
  <div class="composer-root">
    <form
      class="floating-composer"
      :class="{ dragover: dragOver }"
      @submit.prevent="$emit('submit')"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop.prevent="$emit('drop', $event); dragOver = false"
    >
      <slot name="preamble" />
      <textarea
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        rows="1"
        @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
        @keydown.enter.exact.prevent="$emit('submit')"
      />
      <div class="composer-bottom">
        <div class="tool-row">
          <slot name="attach-button" />
          <slot name="tools" />
        </div>
        <button
          class="send"
          :class="{ 'send--stop': actionMode === 'stop' }"
          type="submit"
          :disabled="actionMode === 'send' && (disabled || !(modelValue || '').trim())"
          :title="actionMode === 'stop' ? stopTitle : sendTitle"
          :aria-label="actionMode === 'stop' ? stopTitle : sendTitle"
        >{{ actionMode === 'stop' ? stopLabel : sendLabel }}</button>
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
 * Renders a floating textarea with toolbar and send button.
 * Drag-and-drop support via slots and events.
 */
import { ref } from 'vue'

withDefaults(defineProps<{
  modelValue: string
  placeholder?: string
  disabled?: boolean
  actionMode?: 'send' | 'stop'
  sendLabel?: string
  stopLabel?: string
  sendTitle?: string
  stopTitle?: string
}>(), {
  actionMode: 'send',
  sendLabel: 'send',
  stopLabel: 'stop',
  sendTitle: '发送',
  stopTitle: '停止运行',
})

defineEmits<{
  'update:modelValue': [value: string]
  submit: []
  drop: [event: DragEvent]
}>()

const dragOver = ref(false)
</script>
