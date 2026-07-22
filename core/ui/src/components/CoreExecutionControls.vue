<template>
  <div class="core-execution-controls composer-model-row">
    <slot name="leading" />
    <UiSelect
      v-if="modelOptions.length > 0"
      class="composer-model-select"
      :model-value="modelValue"
      :options="modelOptions"
      :placeholder="modelAriaLabel"
      :aria-label="modelAriaLabel"
      direction="up"
      hide-arrow
      @update:model-value="$emit('update:modelValue', $event)"
    />
    <UiSelect
      class="composer-thinking-select"
      :model-value="thinkingMode"
      :options="combinedThinkingOptions"
      :placeholder="thinkingAriaLabel"
      :aria-label="thinkingAriaLabel"
      direction="up"
      hide-arrow
      @update:model-value="selectThinkingOption"
    />
    <UiSelect
      v-if="modeOptions.length > 0"
      class="composer-mode-select"
      :model-value="activeMode"
      :options="modeOptions"
      :placeholder="'模式'"
      aria-label="操作模式"
      direction="up"
      hide-arrow
      @update:model-value="$emit('update:activeMode', $event)"
    />
    <slot name="trailing" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CoreSelectOption, CoreThinkingMode, CoreThinkingModeOption } from '../composer/execution'
import UiSelect from './UiSelect.vue'

const props = withDefaults(defineProps<{
  modelValue?: string
  modelOptions?: CoreSelectOption[]
  thinkingMode: CoreThinkingMode | string
  thinkingModeOptions: CoreThinkingModeOption[]
  shallowThinkingEnabled?: boolean
  activeMode?: string
  modeOptions?: CoreSelectOption[]
  modelAriaLabel?: string
  thinkingAriaLabel?: string
  shallowLabel?: string
  shallowTitle?: string
}>(), {
  modelValue: '',
  modelOptions: () => [],
  shallowThinkingEnabled: false,
  activeMode: '',
  modeOptions: () => [],
  modelAriaLabel: '模型',
  thinkingAriaLabel: '思考模式',
  shallowLabel: 'Shallow',
  shallowTitle: 'Shallow thinking',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:thinkingMode': [value: string]
  'update:shallowThinkingEnabled': [value: boolean]
  'update:activeMode': [value: string]
}>()

const SHALLOW_OPTION_VALUE = '__shallow__'
const combinedThinkingOptions = computed(() => [
  ...props.thinkingModeOptions,
  {
    value: SHALLOW_OPTION_VALUE,
    label: props.shallowLabel,
    selected: props.shallowThinkingEnabled,
    separatorBefore: true,
    activeAccent: true,
  },
])

function selectThinkingOption(value: string) {
  if (value === SHALLOW_OPTION_VALUE) {
    emit('update:shallowThinkingEnabled', !props.shallowThinkingEnabled)
    return
  }
  emit('update:thinkingMode', value)
}
</script>

<style scoped>
.core-execution-controls.composer-model-row {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0;
}

.core-execution-controls :deep(.ui-select) {
  min-width: 0;
  width: auto;
}

:deep(.ui-select-trigger) {
  width: auto;
  min-width: 0;
  max-width: min(260px, 42vw);
  min-height: 28px;
  height: 28px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  padding: 0 8px;
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 76%, transparent);
  font-size: 12px;
  font-weight: 600;
}

:deep(.ui-select-trigger:hover),
:deep(.ui-select.open .ui-select-trigger) {
  background: color-mix(in srgb, var(--theme-composer-text, currentColor) 8%, transparent);
  color: var(--theme-composer-text, currentColor);
}

:deep(.ui-select-trigger:focus-visible) {
  outline: 2px solid color-mix(in srgb, var(--theme-composer-text, currentColor) 26%, transparent);
  outline-offset: 2px;
}

:deep(.ui-select-menu) {
  z-index: var(--z-popover, 60);
  width: max-content;
  min-width: 100%;
  max-width: min(280px, calc(100vw - 24px));
}

:global(.floating-composer:has(.core-execution-controls .ui-select.open)) {
  overflow: visible;
}

@media (max-width: 560px) {
  :deep(.ui-select-trigger) {
    max-width: 34vw;
  }
}
</style>
