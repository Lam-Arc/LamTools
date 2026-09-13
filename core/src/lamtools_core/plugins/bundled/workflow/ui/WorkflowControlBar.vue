<template>
  <div class="wf-control-bar">
    <button v-if="!running" class="small-btn primary" type="button" aria-label="运行整个工作流" title="运行整个工作流" @click="$emit('run')">
      <Play :size="15" :stroke-width="1.8" aria-hidden="true" />
    </button>
    <button v-else class="small-btn danger" type="button" aria-label="停止工作流" title="停止工作流" @click="$emit('cancel')">
      <Square :size="14" :stroke-width="1.8" aria-hidden="true" />
    </button>
    <button class="small-btn" type="button" :disabled="running" aria-label="单步调试" title="单步调试" @click="$emit('step')">
      <StepForward :size="15" :stroke-width="1.8" aria-hidden="true" />
    </button>
    <button class="small-btn quiet" type="button" :disabled="running || !canUndo" title="撤销（Ctrl/Cmd+Z）" aria-label="撤销" @click="$emit('undo')">
      <Undo2 :size="15" :stroke-width="1.8" aria-hidden="true" />
    </button>
    <button class="small-btn quiet" type="button" :disabled="running || !canRedo" title="重做（Ctrl/Cmd+Shift+Z）" aria-label="重做" @click="$emit('redo')">
      <Redo2 :size="15" :stroke-width="1.8" aria-hidden="true" />
    </button>
    <button
      class="small-btn quiet wf-save-btn"
      type="button"
      :class="{ 'is-dirty': dirty }"
      :disabled="running"
      :title="dirty ? '保存工作流（有未保存修改）' : '保存工作流'"
      :aria-label="dirty ? '保存工作流（有未保存修改）' : '保存工作流'"
      :data-dirty="dirty ? 'true' : 'false'"
      @click="$emit('save')"
    >
      <Save :size="15" :stroke-width="1.8" aria-hidden="true" />
    </button>
    <span v-if="dirty" class="wf-control-status wf-control-dirty" title="有未保存修改" aria-label="有未保存修改">●</span>
    <span v-if="saveError" class="wf-control-status wf-control-error" role="alert" :title="saveError" :aria-label="saveError">
      <CircleAlert :size="15" :stroke-width="1.8" aria-hidden="true" />
    </span>
    <span v-if="conflict" class="wf-control-status wf-control-conflict" role="alert" :title="conflict" :aria-label="conflict">
      <GitCompareArrows :size="15" :stroke-width="1.8" aria-hidden="true" />
    </span>
    <template v-if="conflict">
      <button class="small-btn quiet wf-conflict-action" type="button" :disabled="running" aria-label="采用远端版本" title="放弃本地修改并采用远端版本" @click="$emit('accept-remote')">
        <CloudDownload :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <button class="small-btn quiet wf-conflict-action" type="button" :disabled="running" aria-label="保留本地并重试" title="保留本地修改并用远端版本号重试保存" @click="$emit('keep-local')">
        <CloudUpload :size="15" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </template>
    <span v-if="statusText" class="wf-control-status" role="status" :title="statusText" :aria-label="statusText">
      <Activity :size="15" :stroke-width="1.8" aria-hidden="true" />
    </span>
  </div>
</template>

<script setup lang="ts">
import { Activity, CircleAlert, CloudDownload, CloudUpload, GitCompareArrows, Play, Redo2, Save, Square, StepForward, Undo2 } from 'lucide-vue-next'

defineProps<{
  running?: boolean
  statusText?: string
  dirty?: boolean
  saveError?: string
  conflict?: string
  canUndo?: boolean
  canRedo?: boolean
}>()
defineEmits<{
  run: []
  cancel: []
  step: []
  save: []
  undo: []
  redo: []
  'accept-remote': []
  'keep-local': []
}>()
</script>

<style scoped>
.wf-control-bar {
  display: contents;
}
.wf-control-bar .small-btn,
.wf-control-status {
  display: grid;
  place-items: center;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  min-width: 28px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--theme-main-text);
}
.wf-control-bar .small-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
}
.wf-control-bar .wf-save-btn.is-dirty { color: var(--orange); }
.wf-control-bar .small-btn.danger { color: var(--red); }
.wf-control-bar .small-btn:disabled { cursor: not-allowed; opacity: .42; }
.wf-control-status { font-size: 10px; opacity: .6; }
.wf-control-dirty { color: var(--orange); opacity: 1; }
.wf-control-error { color: var(--red); opacity: 1; }
.wf-control-conflict { color: var(--orange); opacity: 1; }
.wf-conflict-action { color: var(--theme-main-text); }
@media (prefers-reduced-motion: reduce) {
  .wf-control-bar,
  .wf-control-bar * { transition: none; animation: none; }
}
</style>
