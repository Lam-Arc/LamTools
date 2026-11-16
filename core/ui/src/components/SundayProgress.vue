<template>
  <div class="sunday-progress" :class="{ 'sunday-progress--indeterminate': indeterminate }" role="progressbar" :aria-label="label || undefined" :aria-valuemin="0" :aria-valuemax="metrics.maximum" :aria-valuenow="indeterminate ? undefined : metrics.current" :aria-valuetext="valueText || undefined">
    <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(插件、侧栏和更新窗口共享进度反馈，允许未知总量)。 -->
    <span class="sunday-progress__fill" :style="{ width: indeterminate ? '35%' : `${metrics.ratio * 100}%` }" />
  </div>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { progressMetrics } from '@/helpers/progressMetrics.ts'
const props = withDefaults(defineProps<{ value?: unknown; max?: unknown; label?: string; indeterminate?: boolean; valueText?: string }>(), { value: 0, max: 100, label: '', indeterminate: false, valueText: '' })
const metrics = computed(() => progressMetrics(props.value, props.max))
</script>
