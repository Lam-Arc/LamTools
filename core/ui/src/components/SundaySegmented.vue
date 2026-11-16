<template>
  <div
    ref="rootEl"
    class="sunday-segmented"
    role="radiogroup"
    :aria-label="label"
    @keydown="onRadioGroupKeydown"
  >
    <span v-show="hasSelection" ref="indicatorEl" class="sunday-segmented__indicator" aria-hidden="true" />
    <button
      v-for="option in options"
      :key="option.value"
      class="sunday-segmented__item"
      type="button"
      role="radio"
      :aria-checked="option.value === modelValue"
      :tabindex="option.value === entryValue ? 0 : -1"
      @click="select(option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(分段控件与主题单选组共用键盘导航)。
import { onRadioGroupKeydown } from '@/composables/radioGroupKeyboard.ts'

defineOptions({ name: 'SundaySegmented' })

const props = defineProps<{
  modelValue: string
  options: Array<{ value: string; label: string }>
  label: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const rootEl = ref<HTMLElement | null>(null)
const indicatorEl = ref<HTMLElement | null>(null)
// user:“确保视觉、功能和交互不退化”+(选项动态变化导致当前值缺失时，仍可用键盘进入，且不显示错误的选中指示)。
const hasSelection = computed(() => props.options.some(option => option.value === props.modelValue))
const entryValue = computed(() => hasSelection.value ? props.modelValue : props.options[0]?.value)

let observer: ResizeObserver | null = null
let readyFrame = 0

function layout(): void {
  const root = rootEl.value
  const indicator = indicatorEl.value
  if (!root || !indicator) return

  const checked = root.querySelector<HTMLButtonElement>('[role="radio"][aria-checked="true"]')
  if (!checked) return

  const rootRect = root.getBoundingClientRect()
  const itemRect = checked.getBoundingClientRect()
  if (!itemRect.width) return

  // The indicator sits at the padding edge; offsetLeft would depend on the
  // engine's box origin, so measure both boxes and subtract the border.
  const left = itemRect.left - rootRect.left - root.clientLeft
  indicator.style.width = `${itemRect.width}px`
  indicator.style.transform = `translateX(${left}px)`
}

function markReady(): void {
  readyFrame = requestAnimationFrame(() => {
    layout()
    rootEl.value?.setAttribute('data-ready', 'true')
  })
}

function focusValue(value: string): void {
  const root = rootEl.value
  if (!root) return
  const index = props.options.findIndex((option) => option.value === value)
  root.querySelectorAll<HTMLButtonElement>('[role="radio"]')[index]?.focus()
}

function select(value: string): void {
  if (value !== props.modelValue) emit('update:modelValue', value)
  void nextTick(() => {
    layout()
    focusValue(value)
  })
}

onMounted(() => {
  layout()
  markReady()

  if ('ResizeObserver' in window) {
    observer = new ResizeObserver(() => layout())
    if (rootEl.value) observer.observe(rootEl.value)
  }

  // user:“不要留尾巴”+(字体接口不是每个运行环境都有，缺失时跳过这次重排)
  if (typeof document !== 'undefined' && document.fonts?.ready) {
    void document.fonts.ready.then(() => layout())
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  cancelAnimationFrame(readyFrame)
})

watch(
  () => [props.modelValue, ...props.options.flatMap(option => [option.value, option.label])],
  () => {
    void nextTick(() => layout())
  },
)
</script>
