<template>
  <textarea
    ref="el"
    class="auto-textarea"
    :style="{ minHeight: minH }"
    :value="String(modelValue ?? '')"
    :placeholder="placeholder"
    :rows="minRows"
    @input="onInput"
    @blur="$emit('blur')"
  />
</template>

<script setup lang="ts">
import { ref, watch, onMounted, nextTick } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: string | unknown
  placeholder?: string
  minRows?: number
  maxRows?: number
}>(), {
  placeholder: '',
  minRows: 2,
  maxRows: 5,
})

const emit = defineEmits<{ 'update:modelValue': [v: string]; blur: [] }>()
const el = ref<HTMLTextAreaElement>()

// min-height = minRows 行 + 上下 padding，保证内容少时也不缩过 minRows
const minH = `calc(${props.minRows} * 1.55em + 2 * var(--space-1))`

function autoGrow() {
  const ta = el.value
  if (!ta) return
  ta.style.height = 'auto'
  // 封顶到 maxRows 行高；超出则 overflow-y:auto 滚动
  const lineH = parseFloat(getComputedStyle(ta).lineHeight) || 18
  const maxH = props.maxRows * lineH
  ta.style.height = Math.min(ta.scrollHeight, maxH) + 'px'
}

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
  autoGrow()
}

onMounted(autoGrow)
watch(() => props.modelValue, () => nextTick(autoGrow))
</script>

<style scoped>
.auto-textarea {
  width: 100%;
  box-sizing: border-box;
  background: color-mix(in srgb, var(--theme-control-background) 70%, transparent);
  border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent);
  border-radius: var(--radius-sm, 6px);
  color: var(--theme-control-text);
  padding: var(--space-1) var(--space-2);
  font-size: 11px;
  line-height: 1.55;
  font-family: var(--font-mono, monospace);
  resize: none;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.auto-textarea:focus { outline: none; }
</style>
