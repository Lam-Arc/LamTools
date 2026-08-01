<template>
  <div class="wf-node" :class="[`kind-${kind}`, `state-${state}`]">
    <!-- Input ports (left side) -->
    <div v-if="inputPorts.length" class="wf-ports wf-ports-in">
      <div v-for="p in inputPorts" :key="`in-${p.name}`" class="wf-port-row">
        <Handle type="target" :position="Position.Left" :id="p.name" class="wf-handle" />
        <span class="wf-port-label" :title="p.type">{{ p.name }}</span>
      </div>
    </div>

    <!-- Center body: always in edit mode -->
    <div class="wf-node-body" @pointerdown.stop>
      <header class="wf-node-head">
        <input v-model="localTitle" class="wf-title-input" type="text" placeholder="标题" @blur="pushTitle" />
        <span class="wf-node-state">{{ stateDot }}</span>
      </header>

      <!-- AI -->
      <template v-if="kind === 'ai'">
        <WfSelect :model-value="localConfig.mode" :options="modeOptions" @update:model-value="localConfig.mode = $event; pushConfig()" />
        <AutoTextarea v-model="localConfig.instruction" :min-rows="2" :max-rows="4" placeholder="指令…" @blur="pushConfig" />
        <WfSelect :model-value="localConfig.model_id" :options="modelOptions" @update:model-value="localConfig.model_id = $event; pushConfig()" />
      </template>

      <!-- Command: shell command -->
      <template v-else-if="kind === 'command'">
        <AutoTextarea v-model="localConfig.command" :min-rows="2" :max-rows="4" placeholder="command…（curl/git/ffmpeg 等）" @blur="pushConfig" />
      </template>

      <!-- Script: Python (binder: ports-as-variables) -->
      <template v-else-if="kind === 'script'">
        <AutoTextarea v-model="localConfig.script" :min-rows="2" :max-rows="4" placeholder="y = x * 2（输入端口名当变量，给输出端口名赋值）" @blur="pushConfig" />
      </template>

      <!-- Content: each output port value -->
      <template v-else-if="kind === 'content'">
        <div v-for="(p, i) in outputPorts" :key="`cv-${i}`" class="wf-port-edit">
          <span class="wf-field-label">{{ p.name }}</span>
          <AutoTextarea v-model="localPorts[i].value" :min-rows="2" :max-rows="4" placeholder="值" @blur="pushPorts" />
        </div>
      </template>

      <!-- Subgraph -->
      <template v-else-if="kind === 'subgraph'">
        <AutoTextarea v-model="localConfig.workflow_name" :min-rows="2" :max-rows="4" placeholder="工作流名称" @blur="pushConfig" />
        <WfSelect :model-value="localConfig.iterate" :options="iterateOptions" @update:model-value="localConfig.iterate = $event; pushConfig()" />
        <AutoTextarea v-if="localConfig.iterate === 'loop'" v-model="localConfig.condition" :min-rows="2" :max-rows="4" placeholder="退出条件" @blur="pushConfig" />
      </template>
    </div>

    <!-- Output ports (right side) -->
    <div v-if="outputPorts.length" class="wf-ports wf-ports-out">
      <div v-for="p in outputPorts" :key="`out-${p.name}`" class="wf-port-row">
        <span class="wf-port-label" :title="p.type">{{ p.name }}</span>
        <Handle type="source" :position="Position.Right" :id="p.name" class="wf-handle" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import WfSelect from './WfSelect.vue'
import AutoTextarea from './AutoTextarea.vue'
import type { WorkflowNode, WorkflowNodeKind, NodeStateStatus, WorkflowPort } from '../workflow/types'

const props = defineProps<{
  data: { node: WorkflowNode; state?: NodeStateStatus; onToggle?: () => void }
}>()

const node = computed(() => props.data.node)
const kind = computed<WorkflowNodeKind>(() => node.value.kind)
const inputPorts = computed(() => node.value.ports.filter((p) => p.direction === 'in'))
const outputPorts = computed(() => node.value.ports.filter((p) => p.direction === 'out'))
const state = computed<NodeStateStatus>(() => props.data.state ?? 'idle')

const stateDot = computed(() => {
  switch (state.value) {
    case 'running': return '◐'
    case 'done': return '●'
    case 'error': return '✕'
    default: return '○'
  }
})

const updateNode = inject<(id: string, patch: Record<string, unknown>) => void>('wf-update-node', () => {})
const _modelsFn = inject<() => Array<{ id: string; display_name?: string; model_id?: string }>>('wf-models', () => [])
const models = computed(() => _modelsFn())

const localTitle = ref(node.value.title)
const localConfig = ref<Record<string, any>>({ ...node.value.config })
const localPorts = ref<WorkflowPort[]>(node.value.ports.map((p) => ({ ...p })))

const modeOptions = [
  { value: 'single', label: 'single' },
  { value: 'loop', label: 'loop' },
  { value: 'agent', label: 'agent' },
]
const iterateOptions = [
  { value: 'none', label: 'none' },
  { value: 'loop', label: 'loop' },
  { value: 'map', label: 'map' },
]
const modelOptions = computed(() => [
  { value: '', label: '（默认模型）' },
  ...models.value.map((m) => ({ value: m.id, label: m.display_name || m.model_id || m.id })),
])

watch(() => props.data.node, (n) => {
  localTitle.value = n.title
  localConfig.value = { ...n.config }
  localPorts.value = n.ports.map((p) => ({ ...p }))
}, { deep: true })

function pushTitle() { if (localTitle.value !== node.value.title) updateNode(node.value.id, { title: localTitle.value }) }
function pushConfig() { updateNode(node.value.id, { config: localConfig.value }) }
function pushPorts() { updateNode(node.value.id, { ports: localPorts.value }) }
</script>

<style scoped>
.wf-node {
  display: flex;
  align-items: stretch;
  border-radius: var(--radius, 12px);
  border: 1px solid var(--theme-main-border);
  background: var(--theme-main-background);
  color: var(--theme-main-text);
  font-size: 12px;
  box-shadow: var(--shadow);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  overflow: visible;
}
.wf-node.kind-ai { background: color-mix(in srgb, var(--purple) 8%, var(--theme-main-background)); border-color: color-mix(in srgb, var(--purple) 30%, var(--theme-main-border)); }
.wf-node.kind-command { background: color-mix(in srgb, var(--orange) 8%, var(--theme-main-background)); border-color: color-mix(in srgb, var(--orange) 30%, var(--theme-main-border)); }
.wf-node.kind-script { background: color-mix(in srgb, var(--blue) 8%, var(--theme-main-background)); border-color: color-mix(in srgb, var(--blue) 30%, var(--theme-main-border)); }
.wf-node.kind-content { background: color-mix(in srgb, var(--blue) 8%, var(--theme-main-background)); border-color: color-mix(in srgb, var(--blue) 30%, var(--theme-main-border)); }
.wf-node.kind-subgraph { background: color-mix(in srgb, var(--green) 8%, var(--theme-main-background)); border-color: color-mix(in srgb, var(--green) 30%, var(--theme-main-border)); }
.wf-node.state-running { box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 60%, transparent), var(--shadow); }
.wf-node.state-error { box-shadow: 0 0 0 2px color-mix(in srgb, var(--red) 60%, transparent), var(--shadow); }

/* Port rows */
.wf-ports { display: flex; flex-direction: column; justify-content: center; gap: 6px; padding: 8px 0; }
.wf-port-row { display: flex; align-items: center; gap: 6px; position: relative; height: 16px; }
.wf-ports-in .wf-port-row { justify-content: flex-start; padding-left: 14px; }
.wf-ports-out .wf-port-row { justify-content: flex-end; padding-right: 14px; }
.wf-port-label { font-size: 10px; opacity: 0.6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 80px; }

/* Center body */
.wf-node-body { flex: 1 1 auto; padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.wf-node-head { display: flex; align-items: center; gap: 6px; }
.wf-node-icon { font-size: 13px; opacity: 0.9; flex-shrink: 0; }
.wf-title-input {
  flex: 1; min-width: 0; border: 1px solid transparent; border-radius: 4px;
  background: transparent; color: inherit; padding: 2px 4px;
  font-size: 12px; font-weight: 650;
}
.wf-title-input:focus { border-color: var(--theme-main-border); background: var(--theme-main-subtle-background, transparent); }
.wf-node-state { font-size: 11px; opacity: 0.85; flex-shrink: 0; }
.wf-node.state-running .wf-node-state { color: var(--blue); }
.wf-node.state-done .wf-node-state { color: var(--green); }
.wf-node.state-error .wf-node-state { color: var(--red); }

/* Inline fields */
.wf-field {
  width: 100%; box-sizing: border-box; border: 1px solid var(--theme-main-border); border-radius: 4px;
  background: var(--theme-main-subtle-background, transparent); color: inherit;
  padding: 3px 6px; font-size: 11px;
}
.wf-field-text {
  width: 100%; box-sizing: border-box; border: 1px solid var(--theme-main-border); border-radius: 4px;
  background: var(--theme-main-subtle-background, transparent); color: inherit;
  padding: 4px 6px; font-size: 11px; font-family: var(--font-mono, monospace); resize: vertical;
}
.wf-port-edit { display: flex; align-items: center; gap: 6px; }
.wf-field-label { font-size: 10px; opacity: 0.6; min-width: 32px; flex-shrink: 0; }
.wf-port-edit .wf-field { flex: 1; }

/* Handles */
.wf-handle {
  width: 8px; height: 8px; border-radius: 50%;
  background: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
  border: 2px solid var(--theme-main-background);
  position: absolute; top: 50%; transform: translateY(-50%);
}
.wf-ports-in .wf-handle { left: -5px; }
.wf-ports-out .wf-handle { right: -5px; }
.wf-handle:hover { background: var(--blue); transform: translateY(-50%) scale(1.3); }
</style>
