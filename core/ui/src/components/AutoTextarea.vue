<template>
  <textarea
    class="auto-textarea"
    :value="String(modelValue ?? '')"
    :placeholder="placeholder"
    :rows="minRows"
    @input="onInput"
    @blur="$emit('blur')"
  />
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  modelValue: string | unknown
  placeholder?: string
  minRows?: number
  maxRows?: number
}>(), {
  placeholder: '',
  minRows: 2,
  maxRows: 4,
})

const emit = defineEmits<{ 'update:modelValue': [v: string]; blur: [] }>()

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}
</script>

<style scoped>
.auto-textarea {
  width: 100%;
  box-sizing: border-box;
  background: var(--theme-main-subtle-background, transparent);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius-sm, 6px);
  color: inherit;
  padding: 4px 6px;
  font-size: 11px;
  line-height: 1.4;
  font-family: var(--font-mono, monospace);
  resize: none;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
