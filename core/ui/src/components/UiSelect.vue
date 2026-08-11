<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

defineOptions({ name: 'UiSelect' })

type SelectOption = {
  value: string
  label: string
  selectedLabel?: string
  group?: string
  disabled?: boolean
  selected?: boolean
  separatorBefore?: boolean
  activeAccent?: boolean
}

const props = defineProps<{
  modelValue: string
  options: SelectOption[]
  placeholder?: string
  ariaLabel?: string
  /** Direction the menu opens: 'down' (default) or 'up' */
  direction?: 'up' | 'down'
  hideArrow?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const open = ref(false)
const root = ref<HTMLElement | null>(null)

const selectedLabel = computed(() => {
  const option = props.options.find((item) => item.value === props.modelValue)
  return option?.selectedLabel || option?.label?.replace(/^\s*-\s*/, '') || props.placeholder || '未指定'
})

const groupedOptions = computed(() => {
  const groups: Array<{ group: string; options: SelectOption[] }> = []
  const indexByGroup = new Map<string, number>()
  for (const option of props.options) {
    const group = option.group || ''
    let index = indexByGroup.get(group)
    if (index === undefined) {
      index = groups.length
      indexByGroup.set(group, index)
      groups.push({ group, options: [] })
    }
    groups[index].options.push(option)
  }
  return groups
})

function toggle() {
  if (props.disabled) return
  open.value = !open.value
}

function selectOption(option: SelectOption) {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  open.value = false
}

function onPointerDown(event: PointerEvent) {
  const target = event.target as Node | null
  if (!target || !root.value || root.value.contains(target)) return
  open.value = false
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', onPointerDown)
})
</script>

<template>
  <div ref="root" class="ui-select" :class="{ open, 'ui-select--up': direction === 'up' }">
    <button
      class="ui-select-trigger"
      type="button"
      :disabled="disabled"
      :aria-label="ariaLabel || `当前选择：${selectedLabel}`"
      :aria-expanded="open"
      @click="toggle"
    >
      <span>{{ selectedLabel }}</span>
      <span v-if="!hideArrow" class="ui-select-arrow"></span>
    </button>
    <div v-if="open" class="ui-select-menu">
      <div v-for="group in groupedOptions" :key="group.group || 'default'" class="ui-select-group">
        <div v-if="group.group" class="ui-select-group-label">{{ group.group }}</div>
        <button
          v-for="option in group.options"
          :key="option.value"
          class="ui-select-option"
          :class="{
            active: option.selected ?? option.value === modelValue,
            'active-accent': option.activeAccent,
            'separator-before': option.separatorBefore,
            disabled: option.disabled,
          }"
          type="button"
          @click="selectOption(option)"
        >
          {{ option.label }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ui-select {
  position: relative;
  min-width: 0;
}

.ui-select-trigger {
  width: 100%;
  min-height: 32px;
  border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, currentColor var(--alpha-hover), transparent);
  color: inherit;
  padding: 0 var(--space-3) 0 var(--space-2);
  display: inline-flex;
  align-items: center;
  text-align: left;
}

.ui-select-trigger:disabled {
  opacity: 0.45;
  cursor: default;
}

.ui-select-trigger span:first-child {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.ui-select-arrow {
  position: absolute;
  right: 11px;
  top: 50%;
  width: 7px;
  height: 7px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  opacity: .7;
  transform: translateY(-65%) rotate(45deg);
}

.ui-select.open .ui-select-arrow {
  transform: translateY(-35%) rotate(225deg);
}

.ui-select-menu {
  position: absolute;
  left: 0;
  top: calc(100% + 6px);
  z-index: var(--z-popover);
  width: max(280px, 100%);
  max-height: 320px;
  overflow: auto;
  border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
  border-radius: var(--radius);
  background: var(--settings-card-background, var(--theme-composer-background, #242424));
  color: var(--settings-card-text, var(--theme-composer-text, #f4f1ec));
  box-shadow: var(--shadow-md);
  padding: 6px;
  display: grid;
  gap: 4px;
}

.ui-select--up .ui-select-menu {
  top: auto;
  bottom: calc(100% + 6px);
}

.ui-select-group {
  display: grid;
  gap: 2px;
}

.ui-select-group + .ui-select-group {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid color-mix(in srgb, currentColor 12%, transparent);
}

.ui-select-group-label {
  padding: 4px 9px 3px;
  color: color-mix(in srgb, currentColor 72%, transparent);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.35;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.ui-select-option {
  min-height: 30px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: inherit;
  padding: 5px 9px;
  display: block;
  text-align: left;
  font-size: 13px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  position: relative;
}
.ui-select-option::before {
  content: ""; position: absolute; inset: 0;
  border-radius: 0; background: transparent; pointer-events: none;
  -webkit-mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
  mask-image: linear-gradient(to right, rgba(0,0,0,.2) 0, #000 var(--row-fade), #000 calc(100% - var(--row-fade)), rgba(0,0,0,.2) 100%);
}
.ui-select-option:hover::before {
  background: color-mix(in srgb, currentColor var(--alpha-hover), transparent);
}
.ui-select-option.active::before {
  background: color-mix(in srgb, currentColor var(--alpha-active), transparent);
}

.ui-select-option.active.active-accent {
  background: transparent;
  color: var(--green, #32d17d);
}

.ui-select-option.separator-before {
  position: relative;
  margin-top: 7px;
}

.ui-select-option.separator-before::after {
  content: '';
  position: absolute;
  left: 9px;
  right: 9px;
  top: -4px;
  height: 1px;
  background: color-mix(in srgb, currentColor 16%, transparent);
}

.ui-select-option.disabled {
  opacity: .45;
  cursor: default;
}
</style>
