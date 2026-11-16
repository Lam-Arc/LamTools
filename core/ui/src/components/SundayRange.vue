<template>
  <div
    class="sunday-range"
    :class="{ 'sunday-range--bare': bare }"
    :data-disabled="disabled ? 'true' : undefined"
  >
    <div v-if="!bare" class="sunday-range__head">
      <span class="sunday-range__label">{{ label }}</span>
      <span class="sunday-range__value" aria-hidden="true">{{ displayValue }}</span>
    </div>
    <div class="sunday-range__track" :style="trackStyle">
      <span class="sunday-range__fill" aria-hidden="true" />
      <input
        class="sunday-range__input"
        v-bind="inputAttrs"
        type="range"
        :value="modelValue"
        :min="min"
        :max="max"
        :step="step"
        :disabled="disabled"
        :aria-label="label"
        :aria-valuetext="valueText ?? displayValue"
        @input="onInput"
        @change="onChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

defineOptions({ name: 'SundayRange' })

const props = withDefaults(defineProps<{
  modelValue: number
  min?: number
  max?: number
  step?: number
  label?: string
  suffix?: string
  decimals?: number
  disabled?: boolean
  bare?: boolean
  /** user:“通过参数、变体和组合保留必要差异”+(保留调用方对真实原生滑条的标识与表单属性) */
  inputAttrs?: Record<string, string>
  /** user:“保留必要差异”+(支持与原始数值不同的可读单位，例如小数表示百分比)。 */
  valueText?: string
}>(), {
  min: 0,
  max: 100,
  step: 1,
  label: '',
  suffix: '',
  decimals: 0,
  disabled: false,
  bare: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: number]
  change: [value: number]
}>()

const fillPercent = computed(() => {
  const span = props.max - props.min
  if (span <= 0) return 0
  return Math.min(100, Math.max(0, ((props.modelValue - props.min) / span) * 100))
})

const displayValue = computed(() => `${props.modelValue.toFixed(props.decimals)}${props.suffix}`)

const trackStyle = computed<Record<string, string>>(() => ({
  '--sunday-range-fill': `${fillPercent.value}%`,
}))

// user:“通过参数、变体和组合保留必要差异”+(允许调用方在拖动时预览、在原生提交时保存)。
function onChange(event: Event): void {
  emit('change', Number((event.target as HTMLInputElement).value))
}

function onInput(event: Event): void {
  emit('update:modelValue', Number((event.target as HTMLInputElement).value))
}
</script>
