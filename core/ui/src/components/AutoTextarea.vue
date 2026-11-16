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
import { computed, ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'

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
// user:“参数调整、变体对比”+(最少行数变化时同步更新实际输入框高度，而不只更新 rows 属性)
const minH = computed(() => `calc(${props.minRows} * 1.55em + 2 * var(--space-1))`)

function autoGrow() {
  const ta = el.value
  if (!ta) return
  ta.style.height = 'auto'
  // 封顶到 maxRows 行高；超出则 overflow-y:auto 滚动
  // user:“确保视觉、功能和交互不退化”+(行数上限包含内边距和边框，避免最后一行被裁切)。
  const style = getComputedStyle(ta)
  const lineH = parseFloat(style.lineHeight) || 18
  const padding = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0)
  const border = (parseFloat(style.borderTopWidth) || 0) + (parseFloat(style.borderBottomWidth) || 0)
  const borderBox = style.boxSizing === 'border-box'
  const maxH = props.maxRows * lineH + (borderBox ? padding + border : 0)
  const contentH = ta.scrollHeight + (borderBox ? border : -padding)
  ta.style.height = Math.ceil(Math.min(contentH, maxH)) + 'px'
}

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
  autoGrow()
}

// user:“确保视觉、功能和交互不退化”+(布局宽度变化后重新计算换行高度，避免隐藏内容或留下多余空白)。
let resizeObserver: ResizeObserver | null = null
let observedWidth: number | undefined
onMounted(() => {
  autoGrow()
  if (typeof ResizeObserver !== 'undefined' && el.value) {
    resizeObserver = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width
      if (width === undefined || width === observedWidth) return
      observedWidth = width
      autoGrow()
    })
    resizeObserver.observe(el.value)
  } else {
    window.addEventListener('resize', autoGrow)
  }
})
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  window.removeEventListener('resize', autoGrow)
})
watch(() => [props.modelValue, props.minRows, props.maxRows], () => nextTick(autoGrow))

/** 聚焦并把光标落到文本末尾（调用方打开编辑器时用） */
function focus() {
  const ta = el.value
  if (!ta) return
  ta.focus()
  const end = ta.value.length
  ta.setSelectionRange(end, end)
}

defineExpose({ focus })
</script>

<style scoped>
.auto-textarea {
  width: 100%;
  box-sizing: border-box;
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm, 6px);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  padding: var(--space-1) var(--space-2);
  font-size: 11px;
  line-height: 1.55;
  font-family: var(--font-mono, monospace);
  resize: none;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  /* user:“修复输入框缩窄时 @ 标签溢出的问题”+(窄容器里长文件名按任意位置断行，输入框不被内容顶宽)。 */
  overflow-wrap: anywhere;
  min-width: 0;
}
.auto-textarea:focus { outline: none; }
</style>
