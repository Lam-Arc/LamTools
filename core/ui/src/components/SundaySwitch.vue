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
      <!-- user:“通过参数、变体和组合保留必要差异”+(允许业务开关在滑块内显示进行中状态) -->
      <span class="sunday-switch__thumb"><slot name="thumb" /></span>
    </span>
    <!-- user:“把功能相近或者实际相似的样式和组件，统一成一套”+(带文案的开关不再自己搭轨道，
         直接把文案放进同一行，整行可点) -->
    <span v-if="$slots.default" class="sunday-switch__label"><slot /></span>
  </label>
</template>

<script setup lang="ts">
import { nextTick } from 'vue'

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
  // user:“确保视觉、功能和交互不退化”+(受控开关在保存失败或父级未接受变化时恢复真实状态)。
  const input = event.target as HTMLInputElement
  model.value = input.checked
  void nextTick(() => { input.checked = model.value })
}
</script>
