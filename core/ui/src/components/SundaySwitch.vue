<template>
  <label class="sunday-switch" :class="{ 'sunday-switch--sm': size === 'sm' }">
    <input
      class="sunday-switch__input"
      type="checkbox"
      role="switch"
      :checked="model"
      :disabled="disabled"
      :aria-label="label"
      @change="onChange"
    />
    <span class="sunday-switch__track" aria-hidden="true">
      <span class="sunday-switch__thumb" />
    </span>
  </label>
</template>

<script setup lang="ts">
defineOptions({ name: 'SundaySwitch' })

const model = defineModel<boolean>({ default: false })

withDefaults(defineProps<{
  disabled?: boolean
  label: string
  size?: 'sm' | 'md'
}>(), {
  disabled: false,
  size: 'md',
})

function onChange(event: Event): void {
  model.value = (event.target as HTMLInputElement).checked
}
</script>
