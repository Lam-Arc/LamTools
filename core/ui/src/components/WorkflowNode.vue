<template>
  <div class="wf-node" :class="[`kind-${kind}`, `state-${state}`]">
    <Handle
      v-for="p in inputPorts"
      :key="`in-${p.name}`"
      type="target"
      :position="Position.Left"
      :id="p.name"
      class="wf-handle wf-handle-in"
    />
    <header class="wf-node-head">
      <span class="wf-node-icon" aria-hidden="true">{{ icon }}</span>
      <span class="wf-node-title" :title="node.title || node.id">{{ node.title || node.id }}</span>
      <span class="wf-node-state" :title="state">{{ stateDot }}</span>
    </header>
    <p class="wf-node-summary">{{ summary }}</p>
    <Handle
      v-for="p in outputPorts"
      :key="`out-${p.name}`"
      type="source"
      :position="Position.Right"
      :id="p.name"
      class="wf-handle wf-handle-out"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import type { WorkflowNode, WorkflowNodeKind, NodeStateStatus } from '../workflow/types'

const props = defineProps<{
  data: { node: WorkflowNode; state?: NodeStateStatus }
}>()

const node = computed(() => props.data.node)
const kind = computed<WorkflowNodeKind>(() => node.value.kind)
const inputPorts = computed(() => node.value.ports.filter((p) => p.direction === 'in'))
const outputPorts = computed(() => node.value.ports.filter((p) => p.direction === 'out'))
const state = computed<NodeStateStatus>(() => props.data.state ?? 'idle')

const icon = computed(() => {
  if (kind.value === 'llm') return '◇'
  if (kind.value === 'agent') return '◈'
  return '◆'
})

const stateDot = computed(() => {
  switch (state.value) {
    case 'running':
      return '◐'
    case 'done':
      return '●'
    case 'error':
      return '✕'
    case 'skipped':
    case 'cancelled':
      return '○'
    default:
      return '○'
  }
})

const summary = computed(() => {
  const cfg = node.value.config
  if (kind.value === 'llm') {
    const mode = cfg.mode || 'single'
    const tools = Array.isArray(cfg.allowed_tools) ? cfg.allowed_tools.length : 0
    return `${mode}${tools ? ` · ${tools}工具` : ''}`
  }
  if (kind.value === 'agent') {
    const tools = Array.isArray(cfg.tools) ? cfg.tools.length : 0
    return `agent${tools ? ` · ${tools}工具` : ''}`
  }
  const at = cfg.action_type || 'shell'
  return String(at)
})
</script>

<style scoped>
.wf-node {
  min-width: 168px;
  max-width: 220px;
  border-radius: var(--radius, 12px);
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #fff) 12%, transparent);
  background: var(--theme-main-background, #1d1e1e);
  color: var(--theme-main-text, #f2efeb);
  padding: 8px 10px;
  font-size: 12px;
  box-shadow: var(--shadow, 0 2px 8px rgba(0, 0, 0, 0.35));
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.wf-node.kind-llm { border-left: 3px solid var(--purple, #bd8cff); }
.wf-node.kind-agent { border-left: 3px solid var(--green, #32d17d); }
.wf-node.kind-action { border-left: 3px solid var(--orange, #ff9142); }
.wf-node.state-running { box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue, #79bcff) 60%, transparent), var(--shadow, 0 2px 8px rgba(0,0,0,0.35)); }
.wf-node.state-error { box-shadow: 0 0 0 2px color-mix(in srgb, var(--red, #f5555d) 60%, transparent), var(--shadow, 0 2px 8px rgba(0,0,0,0.35)); }
.wf-node-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.wf-node-icon { font-size: 13px; opacity: 0.9; }
.wf-node-title {
  flex: 1;
  font-weight: 650;
  letter-spacing: -0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.wf-node-state { font-size: 11px; opacity: 0.85; }
.wf-node.state-running .wf-node-state { color: var(--blue, #79bcff); }
.wf-node.state-done .wf-node-state { color: var(--green, #32d17d); }
.wf-node.state-error .wf-node-state { color: var(--red, #f5555d); }
.wf-node-summary {
  margin: 4px 0 0;
  opacity: 0.6;
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.wf-handle {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--theme-main-text, #fff) 50%, transparent);
  border: 2px solid var(--theme-main-background, #1d1e1e);
}
</style>
