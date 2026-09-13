<template>
  <div
    class="wf-node"
    :class="[kindClass, `state-${state}`]"
    :data-node-type="nodeTypeId"
    role="group"
    :aria-label="`${node.title || node.id}，${stateLabel}`"
  >
    <!-- Input ports (left side) -->
    <div v-if="inputPorts.length" class="wf-ports wf-ports-in">
      <div v-for="p in inputPorts" :key="`in-${portHandleId(p)}`" class="wf-port-row">
        <Handle type="target" :position="Position.Left" :id="portHandleId(p)" class="wf-handle" />
        <span class="wf-port-label" :title="p.type">{{ p.name }}</span>
      </div>
    </div>

    <!-- Center body: always in edit mode -->
    <div class="wf-node-body" @pointerdown.stop>
      <header class="wf-node-head">
        <span class="wf-node-kind" :title="nodeTypeId">{{ nodeKindLabel }}</span>
        <input v-model="localTitle" class="wf-title-input" type="text" placeholder="标题" @blur="pushTitle" />
        <span class="wf-node-state">
          <component :is="stateDot" :size="11" :stroke-width="2" aria-hidden="true" />
        </span>
      </header>

      <!-- AI -->
      <template v-if="kind === 'ai'">
        <UiSelect :model-value="localConfig.mode" :options="modeOptions" aria-label="AI 模式" @update:model-value="localConfig.mode = $event; pushConfig()" />
        <AutoTextarea v-model="localConfig.instruction" :min-rows="2" :max-rows="4" placeholder="指令…" @blur="pushConfig" />
        <UiSelect :model-value="localConfig.model_id" :options="modelOptions" aria-label="模型" @update:model-value="localConfig.model_id = $event; pushConfig()" />
      </template>

      <!-- Canonical Model and Agent are independent node types. The legacy
           `ai` branch above keeps old graphs working while these two nodes
           expose the same model selector without the old mode multiplexing. -->
      <template v-else-if="kind === 'model' || kind === 'agent'">
        <AutoTextarea v-model="localConfig.instruction" :min-rows="2" :max-rows="4" :placeholder="kind === 'agent' ? 'Agent 目标…' : '模型指令…'" @blur="pushConfig" />
        <UiSelect :model-value="localConfig.model_id" :options="modelOptions" aria-label="模型" @update:model-value="localConfig.model_id = $event; pushConfig()" />
      </template>

      <!-- Command: shell command -->
      <template v-else-if="kind === 'command'">
        <AutoTextarea v-model="localConfig.command" :min-rows="2" :max-rows="4" placeholder="command…（curl/git/ffmpeg 等）" @blur="pushConfig" />
      </template>

      <!-- Script: Python (binder: ports-as-variables) -->
      <template v-else-if="kind === 'script'">
        <AutoTextarea v-model="localConfig.script" :min-rows="2" :max-rows="4" placeholder="y = x * 2（输入端口名当变量，给输出端口名赋值）" @blur="pushConfig" />
      </template>

      <!-- Canonical Python node. `script` remains above as a compatibility
           renderer for old documents; both use the same execution contract. -->
      <template v-else-if="kind === 'python'">
        <AutoTextarea v-model="localConfig.script" :min-rows="2" :max-rows="4" placeholder="y = x * 2（输入端口名当变量，给输出端口名赋值）" @blur="pushConfig" />
      </template>

      <!-- Content: each output port value -->
      <template v-else-if="kind === 'content'">
        <div v-for="p in outputPorts" :key="`cv-${portHandleId(p)}`" class="wf-port-edit">
          <span class="wf-field-label">{{ p.name }}</span>
          <AutoTextarea :model-value="String(portValue(p) ?? '')" :min-rows="2" :max-rows="4" placeholder="值" @update:model-value="setPortValue(p, $event)" @blur="pushPorts" />
        </div>
      </template>

      <!-- Canonical Constant mirrors Content but stores its value in the
           schema/runtime config as well as the visible output port. -->
      <template v-else-if="kind === 'constant'">
        <div v-for="p in outputPorts" :key="`constant-${portHandleId(p)}`" class="wf-port-edit">
          <span class="wf-field-label">{{ p.name }}</span>
          <AutoTextarea :model-value="String(portValue(p) ?? localConfig.value ?? '')" :min-rows="2" :max-rows="4" placeholder="值" @update:model-value="setPortValue(p, $event)" @blur="pushPorts" />
        </div>
      </template>

      <!-- Subgraph -->
      <template v-else-if="kind === 'subgraph'">
        <AutoTextarea v-model="localConfig.workflow_name" :min-rows="2" :max-rows="4" placeholder="工作流名称" @blur="pushConfig" />
        <UiSelect :model-value="localConfig.iterate" :options="iterateOptions" aria-label="迭代模式" @update:model-value="localConfig.iterate = $event; pushConfig()" />
        <AutoTextarea v-if="localConfig.iterate === 'loop'" v-model="localConfig.condition" :min-rows="2" :max-rows="4" placeholder="退出条件" @blur="pushConfig" />
      </template>

      <!-- Model, Agent and custom registry nodes are rendered from the same
           object-info schema that created them. -->
      <template v-else-if="schemaDriven">
        <SchemaNodeEditor
          :schema="schema"
          :model-value="localConfig"
          :ports="localPorts"
          @update:model-value="onSchemaConfig"
          @update:ports="onSchemaPorts"
        />
        <p v-if="!schemaFieldsCount" class="wf-schema-hint">{{ nodeTypeId }}</p>
      </template>

      <p v-else class="wf-node-unsupported">{{ nodeTypeId }}</p>
    </div>

    <!-- Output ports (right side) -->
    <div v-if="outputPorts.length" class="wf-ports wf-ports-out">
      <div v-for="p in outputPorts" :key="`out-${portHandleId(p)}`" class="wf-port-row">
        <span class="wf-port-label" :title="p.type">{{ p.name }}</span>
        <Handle type="source" :position="Position.Right" :id="portHandleId(p)" class="wf-handle" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { Circle, CircleCheck, CircleDot, CircleX, Clock3, type LucideIcon } from 'lucide-vue-next'
import { Handle, Position } from '@vue-flow/core'
import UiSelect from '../../../../../../ui/src/components/UiSelect.vue'
import AutoTextarea from '../../../../../../ui/src/components/AutoTextarea.vue'
import SchemaNodeEditor from './SchemaNodeEditor.vue'
import { schemaFields, workflowNodeTypeId } from './catalog'
import { normalizeNodeStateStatus, type WorkflowNode, type WorkflowNodeKind, type WorkflowNodeSchema, type NodeStateStatus, type WorkflowPort } from './types'

const props = defineProps<{
  data: { node: WorkflowNode; state?: NodeStateStatus; onToggle?: () => void }
}>()

const node = computed(() => props.data.node)
const kind = computed<WorkflowNodeKind>(() => node.value.kind)
const nodeTypeId = computed(() => workflowNodeTypeId({ type_id: node.value.type_id, name: node.value.kind }))
const kindClass = computed(() => `kind-${nodeTypeId.value.replace(/[^a-zA-Z0-9_-]/g, '-') || 'node'}`)
const nodeKindLabel = computed(() => {
  const labels: Record<string, string> = {
    model: 'Model', agent: 'Agent', command: 'Command', python: 'Python',
    constant: 'Constant', input: 'Input', output: 'Output', template: 'Template',
    condition: 'Condition', merge: 'Merge', join: 'Join', subgraph: 'Subgraph',
    ai: 'AI', script: 'Script', content: 'Content', transform: 'Transform', branch: 'Branch',
  }
  return labels[nodeTypeId.value] || nodeTypeId.value || 'Node'
})
const inputPorts = computed(() => node.value.ports.filter((p) => p.direction === 'in'))
const outputPorts = computed(() => node.value.ports.filter((p) => p.direction === 'out'))
const state = computed<NodeStateStatus>(() => normalizeNodeStateStatus(props.data.state))

const stateLabel = computed(() => {
  if (state.value === 'running') return '运行中'
  if (state.value === 'waiting') return '等待中'
  if (state.value === 'done') return '已完成'
  if (state.value === 'error') return '失败'
  if (state.value === 'skipped') return '已跳过'
  if (state.value === 'cancelled') return '已取消'
  return '未运行'
})

const stateDot = computed<LucideIcon>(() => {
  switch (state.value) {
    case 'running': return CircleDot
    case 'waiting': return Clock3
    case 'done': return CircleCheck
    case 'error': return CircleX
    default: return Circle
  }
})

const updateNode = inject<(id: string, patch: Record<string, unknown>) => void>('wf-update-node', () => {})
const _modelsFn = inject<() => Array<{ id: string; display_name?: string; model_id?: string }>>('wf-models', () => [])
const models = computed(() => _modelsFn())
const _schemasFn = inject<() => Record<string, WorkflowNodeSchema>>('wf-node-schemas', () => ({}))
const schema = computed<WorkflowNodeSchema | null>(() => {
  const schemas = _schemasFn()
  return schemas[nodeTypeId.value] || schemas[node.value.kind] || null
})
const schemaDriven = computed(() => Boolean(schema.value) && !['ai', 'model', 'agent', 'command', 'script', 'content', 'constant', 'subgraph', 'python'].includes(nodeTypeId.value))
const schemaFieldsCount = computed(() => schemaFields(schema.value, 'input').length)

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

/** Links use the stable port id when available; the display name stays human-readable. */
function portHandleId(port: WorkflowPort): string {
  return String(port.id || port.name)
}

watch(() => props.data.node, (n) => {
  localTitle.value = n.title
  localConfig.value = { ...n.config }
  localPorts.value = n.ports.map((p) => ({ ...p }))
}, { deep: true })

function pushTitle() { if (localTitle.value !== node.value.title) updateNode(node.value.id, { title: localTitle.value }) }
function pushConfig() { updateNode(node.value.id, { config: localConfig.value }) }
function pushPorts() { updateNode(node.value.id, { ports: localPorts.value }) }
function portValue(port: WorkflowPort): unknown {
  return localPorts.value.find((item) => item.direction === 'out' && (item.id === port.id || item.name === port.name))?.value ?? port.value
}
function setPortValue(port: WorkflowPort, value: unknown): void {
  localPorts.value = localPorts.value.map((item) => (
    item.direction === 'out' && (item.id === port.id || item.name === port.name)
      ? { ...item, value }
      : item
  ))
  if (kind.value === 'constant') localConfig.value = { ...localConfig.value, value }
}
function onSchemaConfig(value: Record<string, unknown>): void {
  localConfig.value = { ...localConfig.value, ...value }
  pushConfig()
}
function onSchemaPorts(value: WorkflowPort[]): void {
  localPorts.value = value.map((port) => ({ ...port }))
  pushPorts()
}
</script>

<style scoped>
.wf-node {
  position: relative;
  isolation: isolate;
  display: flex;
  align-items: stretch;
  border-radius: var(--radius, 12px);
  border: 1px solid var(--theme-main-border);
  background: transparent;
  color: var(--theme-main-text);
  font-size: 12px;
  box-shadow: var(--shadow-sm);
  -webkit-backdrop-filter: blur(var(--space-2)) saturate(1.8) contrast(1.08);
  backdrop-filter: blur(var(--space-2)) saturate(1.8) contrast(1.08);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  overflow: visible;
}
.wf-node::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: -1;
  border-radius: inherit;
  background: var(--theme-main-background);
  opacity: 0.8;
  pointer-events: none;
}
.wf-node.kind-ai { background: color-mix(in srgb, var(--purple) 8%, transparent); border-color: color-mix(in srgb, var(--purple) 30%, var(--theme-main-border)); }
.wf-node.kind-command { background: color-mix(in srgb, var(--orange) 8%, transparent); border-color: color-mix(in srgb, var(--orange) 30%, var(--theme-main-border)); }
.wf-node.kind-script { background: color-mix(in srgb, var(--blue) 8%, transparent); border-color: color-mix(in srgb, var(--blue) 30%, var(--theme-main-border)); }
.wf-node.kind-content { background: color-mix(in srgb, var(--blue) 8%, transparent); border-color: color-mix(in srgb, var(--blue) 30%, var(--theme-main-border)); }
.wf-node.kind-subgraph { background: color-mix(in srgb, var(--green) 8%, transparent); border-color: color-mix(in srgb, var(--green) 30%, var(--theme-main-border)); }
.wf-node.kind-model { background: color-mix(in srgb, var(--purple) 8%, transparent); border-color: color-mix(in srgb, var(--purple) 30%, var(--theme-main-border)); }
.wf-node.kind-agent { background: color-mix(in srgb, var(--green) 8%, transparent); border-color: color-mix(in srgb, var(--green) 30%, var(--theme-main-border)); }
.wf-node.kind-python, .wf-node.kind-constant { background: color-mix(in srgb, var(--blue) 8%, transparent); border-color: color-mix(in srgb, var(--blue) 30%, var(--theme-main-border)); }
.wf-node.state-running { box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 60%, transparent), var(--shadow-sm); }
.wf-node.state-error { box-shadow: 0 0 0 2px color-mix(in srgb, var(--red) 60%, transparent), var(--shadow-sm); }

/* Port rows */
.wf-ports { display: flex; flex-direction: column; justify-content: center; gap: 6px; padding: 8px 0; }
.wf-port-row { display: flex; align-items: center; gap: 6px; position: relative; height: 16px; }
.wf-ports-in .wf-port-row { justify-content: flex-start; padding-left: 14px; }
.wf-ports-out .wf-port-row { justify-content: flex-end; padding-right: 14px; }
.wf-port-label { font-size: 10px; opacity: 0.6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 80px; }

/* Center body */
.wf-node-body { flex: 1 1 auto; padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.wf-node-head { display: flex; align-items: center; gap: 6px; }
.wf-node-kind {
  flex: 0 0 auto;
  max-width: 72px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: color-mix(in srgb, var(--theme-main-text) 52%, transparent);
  font: 10px var(--font-mono, monospace);
}
.wf-node-icon { font-size: 13px; opacity: 0.9; flex-shrink: 0; }
.wf-title-input {
  flex: 1; min-width: 0; border: 0; outline: 0; border-radius: 0;
  background: transparent; color: inherit; padding: 2px 4px;
  font-size: 12px; font-weight: 650;
}
.wf-title-input:focus { background: transparent; }
.wf-node-state { font-size: 11px; opacity: 0.85; flex-shrink: 0; }
.wf-schema-hint, .wf-node-unsupported { margin: 0; color: color-mix(in srgb, var(--theme-main-text) 52%, transparent); font: 10px var(--font-mono, monospace); }
.wf-node.state-running .wf-node-state { color: var(--blue); }
.wf-node.state-waiting .wf-node-state { color: var(--orange); }
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

@media (prefers-reduced-motion: reduce) {
  .wf-node,
  .wf-handle,
  .wf-select-arrow {
    transition: none;
    animation: none;
  }
}
</style>
