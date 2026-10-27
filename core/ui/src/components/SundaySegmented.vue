<template>
  <div
    ref="rootEl"
    class="sunday-segmented"
    role="radiogroup"
    :aria-label="label"
  >
    <span ref="indicatorEl" class="sunday-segmented__indicator" aria-hidden="true" />
    <button
      v-for="(option, index) in options"
      :key="option.value"
      class="sunday-segmented__item"
      type="button"
      role="radio"
      :aria-checked="option.value === modelValue"
      :tabindex="option.value === modelValue ? 0 : -1"
      @click="select(option.value)"
      @keydown="onKeydown($event, index)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

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

function onKeydown(event: KeyboardEvent, index: number): void {
  const last = props.options.length - 1
  let next = index

  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = index === last ? 0 : index + 1
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = index === 0 ? last : index - 1
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = last
  else return

  event.preventDefault()
  const option = props.options[next]
  if (option) select(option.value)
}

onMounted(() => {
  layout()
  markReady()

  if ('ResizeObserver' in window) {
    observer = new ResizeObserver(() => layout())
    if (rootEl.value) observer.observe(rootEl.value)
  }

  document.fonts.ready.then(() => layout())
})

onBeforeUnmount(() => {
  observer?.disconnect()
  cancelAnimationFrame(readyFrame)
})

watch(
  () => props.modelValue,
  () => {
    void nextTick(() => layout())
  },
)
</script>
