<template>
  <div class="core-execution-controls composer-model-row">
    <slot name="leading" />
    <CoreRuntimeMenu
      v-if="showRuntimeMenu"
      :active-mode="activeMode"
      :active-mode-label="runtimeModeLabel"
      :mode-options="modeOptions"
      :permission-preset="permissionPreset"
      :disabled="disabled"
      @update:active-mode="$emit('update:activeMode', $event)"
      @update:permission-preset="$emit('update:permissionPreset', $event)"
    />
    <CoreModelThinkingMenu
      :model-value="modelValue"
      :model-options="modelOptions"
      :thinking-mode="thinkingMode"
      :thinking-mode-options="thinkingModeOptions"
      :shallow-thinking-enabled="shallowThinkingEnabled"
      :model-aria-label="modelAriaLabel"
      :thinking-aria-label="thinkingAriaLabel"
      :shallow-label="shallowLabel"
      :disabled="disabled"
      @update:model-value="$emit('update:modelValue', $event)"
      @update:thinking-mode="$emit('update:thinkingMode', $event)"
      @update:shallow-thinking-enabled="$emit('update:shallowThinkingEnabled', $event)"
    />
    <slot name="trailing" />
  </div>
</template>

<script setup lang="ts">
import type {
  CorePermissionPreset,
  CoreSelectOption,
  CoreThinkingMode,
  CoreThinkingModeOption,
} from '../composer/execution'
import CoreModelThinkingMenu from './CoreModelThinkingMenu.vue'
import CoreRuntimeMenu from './CoreRuntimeMenu.vue'

const props = withDefaults(defineProps<{
  modelValue?: string
  modelOptions?: CoreSelectOption[]
  thinkingMode: CoreThinkingMode | string
  thinkingModeOptions: CoreThinkingModeOption[]
  shallowThinkingEnabled?: boolean
  activeMode?: string
  modeOptions?: CoreSelectOption[]
  permissionPreset?: CorePermissionPreset | string
  runtimeModeLabel?: string
  showRuntimeMenu?: boolean
  disabled?: boolean
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
  permissionPreset: 'ask',
  runtimeModeLabel: '',
  showRuntimeMenu: true,
  disabled: false,
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
  'update:permissionPreset': [value: CorePermissionPreset]
}>()
</script>

<style scoped>
.core-execution-controls.composer-model-row {
  min-width: 0;
  width: 100%;
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.core-execution-controls :deep(.core-runtime-menu),
.core-execution-controls :deep(.core-model-thinking-menu) {
  min-width: 0;
  flex: 0 1 auto;
}

.core-execution-controls :deep(.core-model-thinking-menu) {
  margin-left: auto;
}

:global(.floating-composer:has(.core-execution-controls [data-core-runtime-menu]),
.floating-composer:has(.core-execution-controls [data-core-model-thinking-menu])) {
  overflow: visible;
}
</style>
