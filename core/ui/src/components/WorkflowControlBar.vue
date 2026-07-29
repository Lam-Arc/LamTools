<template>
  <div class="wf-control-bar">
    <button class="small-btn primary" type="button" :disabled="running" @click="$emit('run')" title="运行整个工作流">
      {{ running ? '运行中…' : '▶ 运行' }}
    </button>
    <button class="small-btn" type="button" :disabled="running" @click="$emit('step')" title="单步调试">⤼ 步进</button>
    <button class="small-btn" type="button" :disabled="running" @click="$emit('save')" title="保存">💾 保存</button>
    <button class="small-btn quiet" type="button" @click="$emit('add-node')" title="添加节点">⊕ 节点</button>
    <span class="wf-control-sep" aria-hidden="true"></span>
    <button class="small-btn quiet" type="button" @click="$emit('zoom-out')" title="缩小">−</button>
    <button class="small-btn quiet" type="button" @click="$emit('zoom-reset')" title="重置缩放">1:1</button>
    <button class="small-btn quiet" type="button" @click="$emit('zoom-in')" title="放大">+</button>
    <span v-if="statusText" class="wf-control-status">{{ statusText }}</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  running?: boolean
  statusText?: string
}>()
defineEmits<{
  run: []
  step: []
  save: []
  'add-node': []
  'zoom-in': []
  'zoom-out': []
  'zoom-reset': []
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
.wf-control-sep { width: 1px; height: 18px; background: color-mix(in srgb, var(--theme-composer-text, #fff) 16%, transparent); }
.wf-control-status { font-size: 11px; opacity: 0.6; margin-left: 4px; }
</style>
