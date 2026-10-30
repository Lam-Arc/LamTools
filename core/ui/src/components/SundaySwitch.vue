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
    <!-- user:“把功能相近或者实际相似的样式和组件，统一成一套”+(带文案的开关不再自己搭轨道，
         直接把文案放进同一行，整行可点) -->
    <span v-if="$slots.default" class="sunday-switch__label"><slot /></span>
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
