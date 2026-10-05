<template>
  <div v-if="node" class="wf-edit-card" :style="cardStyle" @pointerdown.stop @click.stop>
    <header class="wf-edit-head">
      <span class="wf-edit-title">编辑节点</span>
      <button class="text-btn" type="button" aria-label="关闭" @click="$emit('close')">
        <X :size="14" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </header>
    <div class="wf-edit-body">
      <label class="field">
        <span class="field-label">标题</span>
        <input v-model="title" type="text" placeholder="节点标题" />
      </label>
      <label class="field">
        <span class="field-label">类型</span>
        <span class="field-value wf-node-type-label">{{ node.type_id || node.kind }}</span>
      </label>

      <SchemaNodeEditor
        v-if="schema"
        :schema="schema"
        :model-value="schemaValues"
        :ports="node.ports"
        :exclude-keys="schemaExcludedKeys"
        @update:model-value="schemaValues = $event"
        @update:ports="useSchemaPorts"
      />

      <!-- Port editor (common to all kinds) -->
      <div class="port-editor">
        <div class="port-section">
          <span class="field-label">输入端口</span>
          <div v-for="(p, i) in inputPorts" :key="'in'+i" class="port-row">
            <input v-model="p.name" type="text" placeholder="名称" class="port-name" />
            <UiSelect
              class="port-type"
              :model-value="p.type"
              :options="portTypeOptions"
              aria-label="输入端口类型"
              menu-align="right"
              :menu-width="132"
              :menu-max-height="260"
              @update:model-value="p.type = $event"
            />
            <button class="port-del" type="button" @click="inputPorts.splice(i, 1)">
              <X :size="11" :stroke-width="2" aria-hidden="true" />
            </button>
          </div>
          <button class="port-add" type="button" @click="inputPorts.push({ name: '', type: 'string' })">+ 添加输入</button>
        </div>
        <div class="port-section">
          <span class="field-label">输出端口</span>
          <div v-for="(p, i) in outputPorts" :key="'out'+i" class="port-row">
            <input v-model="p.name" type="text" placeholder="名称" class="port-name" />
            <UiSelect
              class="port-type"
              :model-value="p.type"
              :options="portTypeOptions"
              direction="up"
              aria-label="输出端口类型"
              menu-align="right"
              :menu-width="132"
              :menu-max-height="260"
              @update:model-value="p.type = $event"
            />
            <AutoTextarea v-if="node.kind === 'content' || node.kind === 'constant'" v-model="p.value" :min-rows="2" :max-rows="4" placeholder="常量值" />
            <button class="port-del" type="button" @click="outputPorts.splice(i, 1)">
              <X :size="11" :stroke-width="2" aria-hidden="true" />
            </button>
          </div>
          <button class="port-add" type="button" @click="outputPorts.push({ name: '', type: 'string', value: '' })">+ 添加输出</button>
        </div>
      </div>

      <!-- AI remains a compatibility editor. Canonical Model and Agent share
           the stable instruction/model fields but do not use AI's mode switch. -->
      <template v-if="['ai', 'model', 'agent'].includes(node.kind)">
        <p v-if="outputPorts.length" class="hint">输出端口 = JSON 字段（强制 JSON 输出）</p>
        <label v-if="node.kind === 'ai'" class="field">
          <span class="field-label">模式</span>
          <UiSelect :model-value="mode" :options="modeOptions" @update:model-value="mode = $event" />
        </label>
        <label v-if="node.kind === 'ai' && mode === 'loop'" class="field">
          <span class="field-label">最大迭代</span>
          <input v-model.number="loopMax" type="number" min="1" />
        </label>
        <label class="field field-wide">
          <span class="field-label">{{ node.kind === 'agent' ? '目标' : '指令' }}（支持 {{ interpHint }} 插值）</span>
          <AutoTextarea v-model="instruction" :min-rows="2" :max-rows="4" :placeholder="node.kind === 'agent' ? '让 agent 完成的目标…' : '系统提示词…'" />
        </label>
        <label v-if="node.kind === 'ai'" class="field field-wide">
          <span class="field-label">输出格式（文本说明，可选）</span>
          <AutoTextarea v-model="outputFormatText" :min-rows="2" :max-rows="4" placeholder="可选：自然语言格式说明" />
        </label>
        <label v-if="node.kind === 'agent'" class="field field-wide">
          <span class="field-label">工具集</span>
          <div class="wf-tool-checklist">
            <label v-for="t in toolList" :key="t.name" class="wf-tool-check">
              <input type="checkbox" :checked="selectedTools.includes(t.name)" @change="toggleTool(t.name)" />
              <span class="wf-tool-name" :title="t.description">{{ t.name }}</span>
            </label>
            <p v-if="!toolList.length" class="wf-tool-empty">暂无可用工具</p>
          </div>
        </label>
        <details class="settings-advanced">
          <summary>高级设置</summary>
          <label class="field"><span class="field-label">模型</span><AutoTextarea v-model="modelId" :min-rows="1" :max-rows="4" placeholder="provider/model" /></label>
          <label class="field"><span class="field-label">温度</span><input v-model.number="temperature" type="number" step="0.1" /></label>
          <label class="field"><span class="field-label">思考等级</span>
            <UiSelect :model-value="reasoningEffort" :options="effortOptions" @update:model-value="reasoningEffort = $event" />
          </label>
          <label class="field"><span class="field-label">max_tokens</span><input v-model.number="maxTokens" type="number" /></label>
          <label class="field"><span class="field-label">top_p</span><input v-model.number="topP" type="number" step="0.05" /></label>
          <label class="field"><span class="field-label">重试次数</span><input v-model.number="retries" type="number" min="0" /></label>
        </details>
      </template>

      <!-- Command: shell -->
      <template v-else-if="node.kind === 'command'">
        <p v-if="outputPorts.length" class="hint">输出端口 = JSON 键名（stdout 是 JSON 时自动拆分）</p>
        <label class="field field-wide"><span class="field-label">命令</span><AutoTextarea v-model="command" :min-rows="2" :max-rows="4" placeholder='curl -s https://… | jq …' /></label>
        <label class="field"><span class="field-label">工作目录</span><AutoTextarea v-model="cwd" :min-rows="1" :max-rows="4" placeholder="（默认 work_root）" /></label>
        <details class="settings-advanced">
          <summary>高级设置</summary>
          <label class="field"><span class="field-label">超时（秒）</span><input v-model.number="timeout" type="number" min="0" /></label>
          <label class="field"><span class="field-label">重试次数</span><input v-model.number="retries" type="number" min="0" /></label>
        </details>
      </template>

      <!-- Script: Python binder -->
      <template v-else-if="node.kind === 'script' || node.kind === 'python'">
        <p v-if="outputPorts.length" class="hint">输出端口 = 给同名变量赋值</p>
        <label class="field field-wide"><span class="field-label">Python 脚本</span><AutoTextarea v-model="command" :min-rows="2" :max-rows="4" placeholder="y = x * 2" /></label>
        <p class="field-hint">{{ scriptContractHint }}</p>
        <details class="settings-advanced">
          <summary>高级设置</summary>
          <label class="field"><span class="field-label">超时（秒）</span><input v-model.number="timeout" type="number" min="0" /></label>
          <label class="field"><span class="field-label">重试次数</span><input v-model.number="retries" type="number" min="0" /></label>
        </details>
      </template>

      <!-- Subgraph (merges loop + map + subworkflow, iterate selects mode) -->
      <template v-else-if="node.kind === 'subgraph'">
        <p class="hint">引用外部工作流，iterate 控制执行模式</p>
        <label class="field">
          <span class="field-label">工作流名称</span>
          <AutoTextarea v-model="subworkflowName" :min-rows="1" :max-rows="4" placeholder="my_sub_workflow" />
        </label>
        <label class="field">
          <span class="field-label">迭代模式</span>
          <UiSelect :model-value="subIterate" :options="iterateOptions" @update:model-value="subIterate = $event" />
        </label>
        <template v-if="subIterate === 'loop'">
          <label class="field"><span class="field-label">最大迭代</span><input v-model.number="loopMaxIter" type="number" min="1" /></label>
          <label class="field field-wide">
            <span class="field-label">退出条件（Python 表达式）</span>
            <AutoTextarea v-model="subLoopCondition" :min-rows="1" :max-rows="4" placeholder="quality >= 0.8" />
          </label>
        </template>
        <label class="field"><span class="field-label">重试次数</span><input v-model.number="retries" type="number" min="0" /></label>
      </template>

      <!-- Error handling (common, collapsible) -->
      <details v-if="canConfigureExecution" class="settings-advanced">
        <summary>错误处理</summary>
        <label class="field">
          <span class="field-label">策略</span>
          <UiSelect :model-value="onErrorStrategy" :options="onErrorOptions" @update:model-value="onErrorStrategy = $event" />
        </label>
        <template v-if="onErrorStrategy === 'fallback'">
          <label class="field"><span class="field-label">降级输出端口</span><AutoTextarea v-model="onErrorFallbackPort" :min-rows="1" :max-rows="4" placeholder="out" /></label>
          <label class="field"><span class="field-label">降级默认值</span><AutoTextarea v-model="onErrorValue" :min-rows="2" :max-rows="4" placeholder="默认值（空=哨兵跳过）" /></label>
        </template>
      </details>

      <!-- Content: no extra config needed — values are in the port editor -->
    </div>
    <footer class="wf-edit-foot">
      <button class="small-btn primary" type="button" @click="apply">应用</button>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import UiSelect from '../../../../../../ui/src/components/UiSelect.vue'
import AutoTextarea from '../../../../../../ui/src/components/AutoTextarea.vue'
import SchemaNodeEditor from './SchemaNodeEditor.vue'
import type { WorkflowNode, WorkflowNodeSchema, WorkflowPort } from './types'

interface SelectOption {
  value: string
  label: string
}

const props = defineProps<{
  node: WorkflowNode
  anchor: { x: number; y: number }
  availableTools?: Array<{ name: string; description: string }>
  schema?: WorkflowNodeSchema | null
}>()
const emit = defineEmits<{
  close: []
  update: [node: WorkflowNode]
}>()

const cardStyle = computed(() => {
  const cardW = 320
  const cardH = 520
  const left = Math.max(12, Math.min(props.anchor.x - cardW / 2, window.innerWidth - cardW - 12))
  const top = Math.max(12, Math.min(props.anchor.y, window.innerHeight - cardH - 12))
  return { left: `${left}px`, top: `${top}px` }
})

const modeOptions: SelectOption[] = [
  { value: 'single', label: '单次 (single)' },
  { value: 'loop', label: '自迭代 (loop)' },
  { value: 'agent', label: '子代理 (agent)' },
]
const effortOptions: SelectOption[] = [
  { value: '', label: '默认' },
  { value: 'minimal', label: 'minimal' },
  { value: 'low', label: 'low' },
  { value: 'medium', label: 'medium' },
  { value: 'high', label: 'high' },
]

// ---- local editable copies ----
const typeOptions = ['string', 'number', 'boolean', 'object', 'array', 'any']
const portTypeOptions = typeOptions.map(t => ({ value: t, label: t }))
const opOptions = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'regex', 'exists']
const onErrorOptions: SelectOption[] = [
  { value: 'abort', label: '中止（默认）' },
  { value: 'fallback', label: '降级输出' },
  { value: 'skip', label: '跳过' },
]
const iterateOptions: SelectOption[] = [
  { value: 'none', label: '调用一次 (none)' },
  { value: 'loop', label: '循环 (loop)' },
  { value: 'map', label: '遍历数组 (map)' },
]
// Plain string shown in hints (kept in script to avoid Vue template {{ }} conflicts).
const interpHint = '{{端口名}}'
const scriptContractHint = '输入端口名直接当变量用（节点 IN a → 代码里用 a）；给输出端口名赋值即输出（OUT y → 代码里 y=...）。不要 print、不要解析 stdin。用 sys.executable 隔离子进程执行，脚本落盘于 .lam/workflow_scripts/<nodeId>.py。新建节点会自动生成带端口变量注释的脚手架。'

// ---- local editable copies ----
const title = ref(props.node.title)

// Port editor: split into inputs/outputs refs for easy add/remove.
interface PortEdit {
  id?: string
  name: string
  type: string
  description?: string
  required?: boolean
  lazy?: boolean
  value?: unknown
}
function toPortEdit(port: WorkflowPort): PortEdit {
  return { ...port }
}
const inputPorts = ref<PortEdit[]>(
  props.node.ports.filter((p) => p.direction === 'in').map(toPortEdit),
)
const outputPorts = ref<PortEdit[]>(
  props.node.ports.filter((p) => p.direction === 'out').map(toPortEdit),
)
const schemaValues = ref<Record<string, unknown>>({ ...props.node.config })

// LLM / Agent
const instruction = ref(String(props.node.config.instruction ?? props.node.config.system_prompt ?? ''))
const outputFormatText = ref(String(props.node.config.output_format_text ?? ''))
const mode = ref(String(props.node.config.mode ?? 'single'))
const loopMax = ref(Number(props.node.config.loop_max_iterations ?? 3))
const allowTools = ref(!!props.node.config.allow_tools)
const selectedTools = ref<string[]>(
  Array.isArray(props.node.config.allowed_tools)
    ? [...(props.node.config.allowed_tools as string[])]
    : Array.isArray(props.node.config.tools)
      ? [...(props.node.config.tools as string[])]
      : [],
)
const toolList = computed(() => props.availableTools ?? [])
function toggleTool(name: string) {
  const idx = selectedTools.value.indexOf(name)
  if (idx >= 0) selectedTools.value.splice(idx, 1)
  else selectedTools.value.push(name)
}
const modelId = ref(String(props.node.config.model_id ?? ''))
const temperature = ref<number | ''>(props.node.config.temperature === undefined ? '' : Number(props.node.config.temperature))
const timeout = ref<number | ''>(props.node.config.timeout === undefined ? '' : Number(props.node.config.timeout))
const reasoningEffort = ref(String(props.node.config.reasoning_effort ?? ''))
const maxTokens = ref<number | ''>(props.node.config.max_tokens === undefined ? '' : Number(props.node.config.max_tokens))
const topP = ref<number | ''>(props.node.config.top_p === undefined ? '' : Number(props.node.config.top_p))
const retries = ref(Number(props.node.config.retries ?? 0))

// Action
const command = ref(String(props.node.config.command ?? props.node.config.script ?? ''))
const cwd = ref(String(props.node.config.cwd ?? ''))

// Branch
// Subgraph
const subworkflowName = ref(String(props.node.config.workflow_name ?? ''))
const subIterate = ref(String(props.node.config.iterate ?? 'none'))
const loopMaxIter = ref(Number(props.node.config.max_iterations ?? 5))
const subLoopCondition = ref(String(props.node.config.condition ?? ''))

// Error handling (common to all kinds with execution)
const onErrorStrategy = ref(String((props.node.config.on_error as Record<string, unknown> | undefined)?.strategy ?? 'abort'))
const onErrorFallbackPort = ref(String((props.node.config.on_error as Record<string, unknown> | undefined)?.fallback_port ?? ''))
const onErrorValue = ref(String((props.node.config.on_error as Record<string, unknown> | undefined)?.error_value ?? ''))

watch(
  () => props.node.id,
  () => {
    title.value = props.node.title
    inputPorts.value = props.node.ports.filter((p) => p.direction === 'in').map(toPortEdit)
    outputPorts.value = props.node.ports.filter((p) => p.direction === 'out').map(toPortEdit)
    schemaValues.value = { ...props.node.config }
    instruction.value = String(props.node.config.instruction ?? props.node.config.system_prompt ?? '')
    command.value = String(props.node.config.command ?? props.node.config.script ?? '')
  },
)

const schemaExcludedKeys = computed(() => {
  if (['ai', 'model', 'agent'].includes(props.node.kind)) return ['instruction', 'system_prompt', 'output_format_text', 'mode', 'loop_max_iterations', 'model_id', 'temperature', 'reasoning_effort', 'max_tokens', 'top_p', 'retries', 'tools', 'allowed_tools', 'allow_tools']
  if (props.node.kind === 'command') return ['command', 'cwd', 'timeout', 'retries']
  if (props.node.kind === 'script' || props.node.kind === 'python') return ['script', 'timeout', 'retries']
  if (props.node.kind === 'subgraph') return ['workflow_name', 'iterate', 'max_iterations', 'condition', 'retries']
  return []
})

const canConfigureExecution = computed(() => !['content', 'constant', 'input', 'output'].includes(props.node.kind))

function useSchemaPorts(next: WorkflowPort[]): void {
  inputPorts.value = next.filter((port) => port.direction === 'in').map(toPortEdit)
  outputPorts.value = next.filter((port) => port.direction === 'out').map(toPortEdit)
}

function apply() {
  // Rebuild ports from the editor refs.
  const ports: WorkflowPort[] = [
    ...inputPorts.value.filter((p) => p.name).map((p) => ({ ...p, name: p.name, type: p.type, direction: 'in' as const })),
    ...outputPorts.value.filter((p) => p.name).map((p) => ({
      ...p,
      name: p.name,
      type: p.type,
      direction: 'out' as const,
    })),
  ]

  const cfg: Record<string, unknown> = { ...props.node.config }
  Object.assign(cfg, schemaValues.value)
  if (['ai', 'model', 'agent'].includes(props.node.kind)) {
    cfg.instruction = instruction.value
    if (props.node.kind === 'ai') {
      cfg.output_format_text = outputFormatText.value
      cfg.mode = mode.value
      if (mode.value === 'loop') cfg.loop_max_iterations = loopMax.value
    }
    if (props.node.kind === 'agent' || (props.node.kind === 'ai' && mode.value === 'agent')) {
      cfg.tools = [...selectedTools.value]
    } else if (props.node.kind === 'ai') {
      cfg.allow_tools = allowTools.value
      if (allowTools.value) cfg.allowed_tools = [...selectedTools.value]
    }
    cfg.model_id = modelId.value
    if (temperature.value !== '') cfg.temperature = temperature.value
    cfg.reasoning_effort = reasoningEffort.value
    if (maxTokens.value !== '') cfg.max_tokens = maxTokens.value
    if (topP.value !== '') cfg.top_p = topP.value
    cfg.retries = retries.value
  } else if (props.node.kind === 'command') {
    cfg.command = command.value
    if (cwd.value) cfg.cwd = cwd.value
    if (timeout.value !== '') cfg.timeout = timeout.value
    cfg.retries = retries.value
  } else if (props.node.kind === 'script' || props.node.kind === 'python') {
    // Auto-extend the scaffold when ports were added/renamed: for each output
    // port whose assignment line (`name =`) is missing from the script, append
    // a `name = None  # TODO` placeholder; for each input port whose name
    // doesn't appear anywhere, append a comment line. Never removes or
    // overwrites existing lines — purely additive.
    let script = command.value
    const outNames = outputPorts.value.map((p) => p.name).filter(Boolean)
    const inNames = inputPorts.value.map((p) => p.name).filter(Boolean)
    const lines = script.split('\n')
    const appended: string[] = []
    for (const n of inNames) {
      if (!script.includes(n)) appended.push(`# 输入：${n}`)
    }
    for (const n of outNames) {
      if (!lines.some((l) => l.trim().startsWith(`${n} =`))) appended.push(`${n} = None`)
    }
    if (appended.length) {
      script = script.trimEnd() + '\n' + appended.join('\n') + '\n'
    }
    cfg.script = script
    command.value = script
    if (timeout.value !== '') cfg.timeout = timeout.value
    cfg.retries = retries.value
  } else if (props.node.kind === 'subgraph') {
    cfg.workflow_name = subworkflowName.value
    cfg.iterate = subIterate.value
    if (subIterate.value === 'loop') {
      cfg.max_iterations = loopMaxIter.value
      cfg.condition = subLoopCondition.value
    }
    cfg.retries = retries.value
  }
  // Error handling config (common to executable kinds).
  if (canConfigureExecution.value && onErrorStrategy.value !== 'abort') {
    const onErr: Record<string, unknown> = { strategy: onErrorStrategy.value }
    if (onErrorStrategy.value === 'fallback') {
      onErr.fallback_port = onErrorFallbackPort.value
      onErr.error_value = onErrorValue.value
    }
    cfg.on_error = onErr
  }
  // content: no config needed — values are in ports.

  emit('update', { ...props.node, title: title.value, config: cfg, ports })
}
</script>

<style scoped>
.wf-edit-card {
  position: fixed;
  z-index: var(--z-popover, 60);
  width: 320px;
  max-height: 520px;
  display: flex;
  flex-direction: column;
  border-radius: var(--radius-lg, 18px);
  border: 1px solid var(--theme-main-border);
  background: var(--theme-main-background);
  color: var(--theme-main-text);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.wf-edit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--theme-main-border);
}
.wf-edit-title { font-size: 13px; font-weight: 650; }
.wf-edit-body {
  padding: 12px 14px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.wf-edit-foot {
  padding: 8px 14px;
  border-top: 1px solid var(--theme-main-border);
  display: flex;
  justify-content: flex-end;
}
.wf-edit-card :deep(.field) { display: flex; flex-direction: column; gap: 4px; }
.wf-edit-card :deep(.field-wide) { grid-column: 1 / -1; }
.wf-edit-card :deep(.field-label) { font-size: 11px; opacity: 0.65; }
.wf-node-type-label {
  display: block;
  min-height: 30px;
  box-sizing: border-box;
  padding: 6px 8px;
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius-sm);
  background: var(--theme-main-subtle-background);
  color: color-mix(in srgb, var(--theme-main-text) 68%, transparent);
  font: 11px var(--font-mono, monospace);
}
.wf-edit-card :deep(.field-hint) { font-size: 10.5px; opacity: 0.5; line-height: 1.4; margin: 0; }
.wf-edit-card :deep(.field input),
.wf-edit-card :deep(.field textarea) {
  width: 100%;
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm, 6px);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  padding: 6px 8px;
  font-size: 12px;
}
.wf-edit-card :deep(.field textarea) { min-height: 60px; resize: vertical; font-family: var(--font-mono, monospace); }
.wf-edit-card :deep(.toggle-line) { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.wf-edit-card :deep(.settings-advanced) { border-top: 1px solid var(--theme-main-border); padding-top: 8px; }
.wf-edit-card :deep(.settings-advanced summary) { font-size: 11px; opacity: 0.65; cursor: pointer; }

.hint { margin: 0; font-size: 10px; opacity: 0.5; line-height: 1.3; }

.port-editor { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--theme-main-border); border-bottom: 1px solid var(--theme-main-border); padding: 8px 0; }
.port-section { display: flex; flex-direction: column; gap: 4px; }
.port-row { display: flex; align-items: center; gap: 4px; }
.port-name { flex: 1 1 auto; min-width: 0; }
.port-type {
  flex: 0 0 auto;
  width: 82px;
  min-width: 0;
}
.port-type :deep(.ui-select-trigger) {
  min-height: 24px;
  background: var(--theme-main-subtle-background);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius-sm, 6px);
  color: inherit;
  padding: 0 16px 0 6px;
  font-size: 11px;
}
.port-value { flex: 1 1 auto; min-width: 0; background: var(--theme-main-subtle-background); border: 1px solid var(--theme-main-border); border-radius: var(--radius-sm, 6px); color: inherit; padding: 4px 6px; font-size: 11px; }
.port-del {
  flex: 0 0 auto; border: none; background: transparent;
  color: var(--red, #f5555d); cursor: pointer; font-size: 13px; padding: 2px 4px;
  border-radius: 4px;
}
.port-del:hover { background: var(--theme-main-soft-background); }
.port-add {
  align-self: flex-start; border: 1px dashed var(--theme-main-border);
  background: transparent; color: var(--theme-main-text); opacity: 0.6;
  font-size: 11px; padding: 3px 8px; border-radius: var(--radius-sm); cursor: pointer;
}
.port-add:hover { opacity: 1; }

.branch-row { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.branch-field { flex: 1 1 80px; min-width: 0; background: var(--theme-main-subtle-background); border: 1px solid var(--theme-main-border); border-radius: var(--radius-sm, 6px); color: inherit; padding: 4px 6px; font-size: 11px; }
.branch-value { flex: 1 1 60px; min-width: 0; background: var(--theme-main-subtle-background); border: 1px solid var(--theme-main-border); border-radius: var(--radius-sm, 6px); color: inherit; padding: 4px 6px; font-size: 11px; }

.wf-tool-checklist {
  max-height: 168px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 3px;
  border-radius: var(--radius-sm);
  background: var(--theme-main-subtle-background);
}
.wf-tool-check {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 4px 7px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
  line-height: 1.3;
}
.wf-tool-check:hover { background: var(--theme-main-soft-background); }
.wf-tool-check input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  flex: 0 0 auto;
  width: 11px;
  height: 11px;
  margin: 0;
  border-radius: 3px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 35%, transparent);
  background: transparent;
  cursor: pointer;
  position: relative;
  transition: background 0.12s, border-color 0.12s;
}
.wf-tool-check input[type="checkbox"]:checked {
  background: var(--blue);
  border-color: var(--blue);
}
.wf-tool-check input[type="checkbox"]:checked::after {
  content: "";
  position: absolute;
  left: 3px;
  top: 0px;
  width: 4px;
  height: 7px;
  border: solid color-mix(in srgb, var(--theme-backdrop-text) 92%, transparent);
  border-width: 0 1.6px 1.6px 0;
  transform: rotate(45deg);
}
.wf-tool-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.wf-tool-empty { margin: 0; padding: 4px; font-size: 11px; opacity: 0.5; }
</style>
