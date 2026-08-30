<template>
  <div class="wf-control-bar">
    <button v-if="!running" class="small-btn primary" type="button" @click="$emit('run')" title="运行整个工作流">
      <Play :size="12" :stroke-width="2" aria-hidden="true" />
      运行
    </button>
    <button v-else class="small-btn danger" type="button" @click="$emit('cancel')" title="停止工作流">
      停止
    </button>
    <button class="small-btn" type="button" :disabled="running" @click="$emit('step')" title="单步调试">
      <StepForward :size="12" :stroke-width="2" aria-hidden="true" /> 步进
    </button>
    <button class="small-btn" type="button" :disabled="running" @click="$emit('save')" title="保存">
      <Save :size="12" :stroke-width="2" aria-hidden="true" /> 保存
    </button>
    <button class="small-btn quiet" type="button" :class="{ 'is-on': exposed }" :disabled="running" @click="$emit('toggle-exposed')" :title="exposed ? '取消暴露为工具' : '暴露为 Agent 工具'">
      {{ exposed ? '已暴露' : '暴露为工具' }}
    </button>
    <span v-if="statusText" class="wf-control-status">{{ statusText }}</span>
  </div>
</template>

<script setup lang="ts">
import { Play, Save, StepForward } from 'lucide-vue-next'

defineProps<{
  running?: boolean
  exposed?: boolean
  statusText?: string
}>()
defineEmits<{
  run: []
  cancel: []
  step: []
  save: []
  'toggle-exposed': []
}>()
</script>

<style scoped>
.wf-control-bar {
  position: absolute;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  z-index: var(--z-composer, 40);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 20px;
  background: color-mix(in srgb, var(--theme-composer-background, #262625) 92%, transparent);
  border: 1px solid color-mix(in srgb, var(--theme-composer-text, #fff) 12%, transparent);
  box-shadow: var(--shadow, 0 8px 32px rgba(0, 0, 0, 0.5));
  backdrop-filter: blur(8px);
}
.wf-control-bar .small-btn { font-size: 12px; padding: 6px 12px; }
.wf-control-bar .small-btn.danger { color: var(--red); }
.wf-control-bar .small-btn.is-on { color: var(--green); }
.wf-control-status { font-size: 11px; opacity: 0.6; margin-left: 4px; }
</style>
