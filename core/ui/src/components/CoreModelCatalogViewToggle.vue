<template>
  <div class="model-catalog-view-toggle" role="group" aria-label="模型分类方式">
    <button
      v-for="option in options"
      :key="option.value"
      class="model-catalog-view-toggle__option"
      :class="{ 'is-active': modelValue === option.value }"
      type="button"
      :aria-pressed="modelValue === option.value ? 'true' : 'false'"
      :data-model-catalog-view="option.value"
      @click="$emit('update:modelValue', option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import type { CoreModelCatalogView } from '../composer/execution'

defineProps<{
  modelValue: CoreModelCatalogView
}>()

defineEmits<{
  'update:modelValue': [value: CoreModelCatalogView]
}>()

const options: Array<{ value: CoreModelCatalogView; label: string }> = [
  { value: 'group', label: '按组' },
  { value: 'provider', label: '按供应商' },
]
</script>

<style scoped>
.model-catalog-view-toggle {
  --text: var(--theme-control-text);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1);
  border: 1px solid color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  border-radius: var(--radius);
  background: var(--theme-control-background);
  color: var(--text);
}

.model-catalog-view-toggle__option {
  min-height: 26px;
  padding: 0 var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 68%, transparent);
  font: inherit;
  font-size: 11px;
  font-weight: 750;
  cursor: pointer;
}

.model-catalog-view-toggle__option:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.model-catalog-view-toggle__option.is-active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  color: var(--text);
}

.model-catalog-view-toggle__option:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 28%, transparent);
  outline-offset: 1px;
}
</style>
