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
        type="range"
        :value="modelValue"
        :min="min"
        :max="max"
        :step="step"
        :disabled="disabled"
        :aria-label="label"
        :aria-valuetext="displayValue"
        @input="onInput"
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

function onInput(event: Event): void {
  emit('update:modelValue', Number((event.target as HTMLInputElement).value))
}
</script>
