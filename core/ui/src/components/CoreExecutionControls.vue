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
      @update:model-value="$emit('update:modelValue', $event)"
    />
    <UiSelect
      class="composer-thinking-select"
      :model-value="thinkingMode"
      :options="thinkingModeOptions"
      :placeholder="thinkingAriaLabel"
      :aria-label="thinkingAriaLabel"
      direction="up"
      @update:model-value="$emit('update:thinkingMode', $event)"
    />
    <button
      class="core-execution-toggle composer-shallow-toggle"
      :class="{ active: shallowThinkingEnabled }"
      type="button"
      :title="shallowTitle"
      :aria-label="shallowTitle"
      :aria-pressed="shallowThinkingEnabled"
      @click="$emit('update:shallowThinkingEnabled', !shallowThinkingEnabled)"
    >
      {{ shallowLabel }}
    </button>
    <slot name="trailing" />
  </div>
</template>

<script setup lang="ts">
import type { CoreSelectOption, CoreThinkingMode, CoreThinkingModeOption } from '../composer/execution'
import UiSelect from './UiSelect.vue'

withDefaults(defineProps<{
  modelValue?: string
  modelOptions?: CoreSelectOption[]
  thinkingMode: CoreThinkingMode | string
  thinkingModeOptions: CoreThinkingModeOption[]
  shallowThinkingEnabled?: boolean
  modelAriaLabel?: string
  thinkingAriaLabel?: string
  shallowLabel?: string
  shallowTitle?: string
}>(), {
  modelValue: '',
  modelOptions: () => [],
  shallowThinkingEnabled: false,
  modelAriaLabel: '模型',
  thinkingAriaLabel: '思考模式',
  shallowLabel: 'Shallow',
  shallowTitle: 'Shallow thinking',
})

defineEmits<{
  'update:modelValue': [value: string]
  'update:thinkingMode': [value: string]
  'update:shallowThinkingEnabled': [value: boolean]
}>()
</script>

<style scoped>
.core-execution-controls {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.composer-model-select,
.composer-thinking-select {
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
  padding: 0 26px 0 8px;
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

:deep(.ui-select-arrow) {
  right: 10px;
}

:deep(.ui-select-menu) {
  z-index: var(--z-popover, 60);
}

.core-execution-toggle {
  height: 28px;
  padding: 0 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-composer-text, currentColor) 70%, transparent);
  box-shadow: none;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  line-height: 28px;
  cursor: pointer;
}

.core-execution-toggle:hover {
  background: color-mix(in srgb, var(--theme-composer-text, currentColor) 8%, transparent);
  color: var(--theme-composer-text, currentColor);
}

.core-execution-toggle.active {
  background: transparent;
  color: var(--green, #5fca87);
}

.core-execution-toggle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--theme-composer-text, currentColor) 26%, transparent);
  outline-offset: 2px;
}

:global(.floating-composer:has(.core-execution-controls .ui-select.open)) {
  overflow: visible;
}

@media (max-width: 560px) {
  .core-execution-controls {
    gap: 4px;
  }

  :deep(.ui-select-trigger) {
    max-width: 34vw;
  }
}
</style>
