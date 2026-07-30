<template>
  <div class="wf-select" :class="{ open }">
    <button type="button" class="wf-select-trigger" @click="open = !open">
      <span>{{ currentLabel }}</span>
      <svg class="wf-select-arrow" :class="{ flipped: open }" width="8" height="5" viewBox="0 0 8 5"><path fill="currentColor" d="M0 0l4 5 4-5z"/></svg>
    </button>
    <div v-if="open" class="wf-select-menu">
      <button
        v-for="opt in options"
        :key="opt.value"
        type="button"
        class="wf-select-option"
        :class="{ active: opt.value === modelValue }"
        @click="select(opt.value)"
      >{{ opt.label }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

interface Option { value: string; label: string }
const props = defineProps<{
  modelValue: string
  options: Option[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const open = ref(false)
const currentLabel = computed(() => {
  const found = props.options.find((o) => o.value === props.modelValue)
  return found ? found.label : props.modelValue || '—'
})

function select(val: string) {
  emit('update:modelValue', val)
  open.value = false
}

function onOutside(e: PointerEvent) {
  const el = e.target as HTMLElement
  if (!el.closest('.wf-select')) open.value = false
}

onMounted(() => document.addEventListener('pointerdown', onOutside))
onUnmounted(() => document.removeEventListener('pointerdown', onOutside))
</script>

<style scoped>
.wf-select { position: relative; width: 100%; }
.wf-select-trigger {
  width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 4px;
  border: 1px solid var(--theme-main-border); border-radius: 4px;
  background: var(--theme-main-subtle-background, transparent); color: inherit;
  padding: 3px 8px; font-size: 11px; cursor: pointer; box-sizing: border-box;
}
.wf-select-trigger:hover { border-color: color-mix(in srgb, var(--theme-main-text) 30%, var(--theme-main-border)); }
.wf-select-arrow { opacity: 0.5; transition: transform 0.15s; flex-shrink: 0; }
.wf-select-arrow.flipped { transform: rotate(180deg); }

.wf-select-menu {
  position: absolute;
  top: calc(100% + 2px);
  left: 0; right: 0;
  z-index: 100;
  display: flex; flex-direction: column;
  max-height: 130px;
  overflow-y: auto;
  border: 1px solid var(--theme-main-border); border-radius: 5px;
  background: var(--theme-main-background);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}
.wf-select-option {
  width: 100%; text-align: left;
  border: none; background: transparent; color: inherit;
  padding: 5px 10px; font-size: 11px; cursor: pointer;
}
.wf-select-option:hover { background: var(--theme-main-soft-background, color-mix(in srgb, var(--theme-main-text) 8%, transparent)); }
.wf-select-option.active { color: var(--blue); font-weight: 600; }
</style>
