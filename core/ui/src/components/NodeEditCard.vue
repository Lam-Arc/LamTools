<template>
  <div v-if="node" class="wf-edit-card" :style="cardStyle" @pointerdown.stop @click.stop>
    <header class="wf-edit-head">
      <span class="wf-edit-title">编辑节点</span>
      <button class="text-btn" type="button" aria-label="关闭" @click="$emit('close')">✕</button>
    </header>
    <div class="wf-edit-body">
      <label class="field">
        <span class="field-label">标题</span>
        <input v-model="title" type="text" placeholder="节点标题" />
      </label>
      <label class="field">
        <span class="field-label">类型</span>
        <UiSelect :model-value="node.kind" :options="kindOptions" :hide-arrow="true" @update:model-value="onKind" />
      </label>

      <!-- LLM -->
      <template v-if="node.kind === 'llm'">
        <label class="field field-wide">
          <span class="field-label">指令 / 系统提示词</span>
          <textarea v-model="instruction" rows="4" placeholder="系统提示词…"></textarea>
        </label>
        <label class="field field-wide">
          <span class="field-label">输出格式（文本说明）</span>
          <textarea v-model="outputFormatText" rows="2" placeholder="可选：自然语言格式说明"></textarea>
        </label>
        <label class="field">
          <span class="field-label">模式</span>
          <UiSelect :model-value="mode" :options="modeOptions" @update:model-value="mode = $event" />
        </label>
        <label v-if="mode === 'loop'" class="field">
          <span class="field-label">最大迭代</span>
          <input v-model.number="loopMax" type="number" min="1" />
        </label>
        <label class="toggle-line">
          <input v-model="allowTools" type="checkbox" />
          <span>允许工具调用</span>
        </label>
        <label v-if="allowTools" class="field field-wide">
          <span class="field-label">允许的工具</span>
          <div class="wf-tool-checklist">
            <label v-for="t in toolList" :key="t.name" class="wf-tool-check">
              <input
                type="checkbox"
                :checked="selectedTools.includes(t.name)"
                @change="toggleTool(t.name)"
              />
              <span class="wf-tool-name" :title="t.description">{{ t.name }}</span>
            </label>
            <p v-if="!toolList.length" class="wf-tool-empty">暂无可用工具</p>
          </div>
        </label>
        <details class="settings-advanced">
          <summary>高级设置</summary>
          <label class="field"><span class="field-label">模型</span><input v-model="modelId" type="text" placeholder="provider/model" /></label>
          <label class="field"><span class="field-label">温度</span><input v-model.number="temperature" type="number" step="0.1" /></label>
          <label class="field"><span class="field-label">思考等级</span>
            <UiSelect :model-value="reasoningEffort" :options="effortOptions" @update:model-value="reasoningEffort = $event" />
          </label>
          <label class="field"><span class="field-label">max_tokens</span><input v-model.number="maxTokens" type="number" /></label>
          <label class="field"><span class="field-label">top_p</span><input v-model.number="topP" type="number" step="0.05" /></label>
          <label class="field"><span class="field-label">重试次数</span><input v-model.number="retries" type="number" min="0" /></label>
        </details>
      </template>

      <!-- Agent -->
      <template v-else-if="node.kind === 'agent'">
        <label class="field field-wide">
          <span class="field-label">目标 / 指令</span>
          <textarea v-model="instruction" rows="4" placeholder="让 agent 完成的目标…"></textarea>
        </label>
        <label class="field field-wide">
          <span class="field-label">工具集</span>
          <div class="wf-tool-checklist">
            <label v-for="t in toolList" :key="t.name" class="wf-tool-check">
              <input
                type="checkbox"
                :checked="selectedTools.includes(t.name)"
                @change="toggleTool(t.name)"
              />
              <span class="wf-tool-name" :title="t.description">{{ t.name }}</span>
            </label>
            <p v-if="!toolList.length" class="wf-tool-empty">暂无可用工具</p>
          </div>
        </label>
        <details class="settings-advanced">
          <summary>高级设置</summary>
          <label class="field"><span class="field-label">模型</span><input v-model="modelId" type="text" /></label>
          <label class="field"><span class="field-label">思考等级</span>
            <UiSelect :model-value="reasoningEffort" :options="effortOptions" @update:model-value="reasoningEffort = $event" />
          </label>
          <label class="field"><span class="field-label">温度</span><input v-model.number="temperature" type="number" step="0.1" /></label>
          <label class="field"><span class="field-label">最大轮次</span><input v-model.number="maxTokens" type="number" /></label>
          <label class="field"><span class="field-label">重试次数</span><input v-model.number="retries" type="number" min="0" /></label>
        </details>
      </template>

      <!-- Action -->
      <template v-else>
        <label class="field">
          <span class="field-label">动作类型</span>
          <UiSelect :model-value="actionType" :options="actionOptions" @update:model-value="onActionType" />
        </label>
        <template v-if="actionType === 'shell'">
          <label class="field field-wide"><span class="field-label">命令</span><textarea v-model="command" rows="3" placeholder='echo "hi"'></textarea></label>
          <label class="field"><span class="field-label">工作目录</span><input v-model="cwd" type="text" placeholder="（默认 work_root）" /></label>
        </template>
        <template v-else-if="actionType === 'script'">
          <label class="field"><span class="field-label">语言</span>
            <UiSelect :model-value="language" :options="langOptions" @update:model-value="language = $event" />
          </label>
          <label class="field field-wide"><span class="field-label">脚本</span><textarea v-model="command" rows="5" placeholder="print('hi')"></textarea></label>
        </template>
        <template v-else-if="actionType === 'http'">
          <label class="field field-wide"><span class="field-label">URL</span><input v-model="command" type="text" placeholder="https://…" /></label>
          <label class="field"><span class="field-label">方法</span>
            <UiSelect :model-value="language" :options="methodOptions" @update:model-value="language = $event" />
          </label>
        </template>
        <details class="settings-advanced">
          <summary>高级设置</summary>
          <label class="field"><span class="field-label">超时（秒）</span><input v-model.number="temperature" type="number" /></label>
          <label class="field"><span class="field-label">重试次数</span><input v-model.number="retries" type="number" min="0" /></label>
        </details>
      </template>
    </div>
    <footer class="wf-edit-foot">
      <button class="small-btn primary" type="button" @click="apply">应用</button>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import UiSelect from './UiSelect.vue'
import type { WorkflowNode, WorkflowNodeKind, ActionKind } from '../workflow/types'

interface SelectOption {
  value: string
  label: string
}

const props = defineProps<{
  node: WorkflowNode
  anchor: { x: number; y: number }
  availableTools?: Array<{ name: string; description: string }>
}>()
const emit = defineEmits<{
  close: []
  update: [node: WorkflowNode]
}>()

const cardStyle = computed(() => {
  const cardW = 320
  const cardH = 420
  // anchor is treated as the desired center; clamp so the card stays on-screen.
  const left = Math.max(12, Math.min(props.anchor.x - cardW / 2, window.innerWidth - cardW - 12))
  const top = Math.max(12, Math.min(props.anchor.y, window.innerHeight - cardH - 12))
  return { left: `${left}px`, top: `${top}px` }
})

const kindOptions: SelectOption[] = [
  { value: 'llm', label: 'LLM' },
  { value: 'agent', label: 'Agent' },
  { value: 'action', label: 'Action' },
]
const modeOptions: SelectOption[] = [
  { value: 'single', label: '单次' },
  { value: 'loop', label: 'loop' },
]
const effortOptions: SelectOption[] = [
  { value: '', label: '默认' },
  { value: 'minimal', label: 'minimal' },
  { value: 'low', label: 'low' },
  { value: 'medium', label: 'medium' },
  { value: 'high', label: 'high' },
]
const actionOptions: SelectOption[] = [
  { value: 'shell', label: 'Shell / 程序命令' },
  { value: 'script', label: '脚本执行' },
  { value: 'http', label: 'HTTP / 网络请求' },
  { value: 'file-data', label: '文件 / 数据变换' },
]
const langOptions: SelectOption[] = [
  { value: 'python', label: 'Python' },
  { value: 'javascript', label: 'JavaScript' },
]
const methodOptions: SelectOption[] = [
  { value: 'GET', label: 'GET' },
  { value: 'POST', label: 'POST' },
  { value: 'PUT', label: 'PUT' },
  { value: 'DELETE', label: 'DELETE' },
]

// local editable copies
const title = ref(props.node.title)
const instruction = ref(String(props.node.config.instruction ?? props.node.config.system_prompt ?? ''))
const outputFormatText = ref(String(props.node.config.output_format_text ?? ''))
const mode = ref(String(props.node.config.mode ?? 'single'))
const loopMax = ref(Number(props.node.config.loop_max_iterations ?? 3))
const allowTools = ref(!!props.node.config.allow_tools)
// Selected tool names (checkbox list, not free text).
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
const reasoningEffort = ref(String(props.node.config.reasoning_effort ?? ''))
const maxTokens = ref<number | ''>(props.node.config.max_tokens === undefined ? '' : Number(props.node.config.max_tokens))
const topP = ref<number | ''>(props.node.config.top_p === undefined ? '' : Number(props.node.config.top_p))
const retries = ref(Number(props.node.config.retries ?? 0))
const actionType = ref(String(props.node.config.action_type ?? 'shell') as ActionKind)
const language = ref(String(props.node.config.language ?? 'python'))
const command = ref(String(props.node.config.command ?? props.node.config.script ?? props.node.config.url ?? ''))
const cwd = ref(String(props.node.config.cwd ?? ''))

watch(
  () => props.node.id,
  () => {
    // reset on node switch
    title.value = props.node.title
    instruction.value = String(props.node.config.instruction ?? props.node.config.system_prompt ?? '')
    command.value = String(props.node.config.command ?? props.node.config.script ?? props.node.config.url ?? '')
    actionType.value = String(props.node.config.action_type ?? 'shell') as ActionKind
  },
)

function onKind(v: string) {
  emit('update', { ...props.node, kind: v as WorkflowNodeKind })
}
function onActionType(v: string) {
  actionType.value = v as ActionKind
}

function apply() {
  const cfg: Record<string, unknown> = { ...props.node.config }
  if (props.node.kind === 'llm') {
    cfg.instruction = instruction.value
    cfg.output_format_text = outputFormatText.value
    cfg.mode = mode.value
    if (mode.value === 'loop') cfg.loop_max_iterations = loopMax.value
    cfg.allow_tools = allowTools.value
    if (allowTools.value) cfg.allowed_tools = [...selectedTools.value]
    cfg.model_id = modelId.value
    if (temperature.value !== '') cfg.temperature = temperature.value
    cfg.reasoning_effort = reasoningEffort.value
    if (maxTokens.value !== '') cfg.max_tokens = maxTokens.value
    if (topP.value !== '') cfg.top_p = topP.value
    cfg.retries = retries.value
  } else if (props.node.kind === 'agent') {
    cfg.instruction = instruction.value
    cfg.tools = [...selectedTools.value]
    cfg.model_id = modelId.value
    cfg.reasoning_effort = reasoningEffort.value
    if (temperature.value !== '') cfg.temperature = temperature.value
    cfg.retries = retries.value
  } else {
    cfg.action_type = actionType.value
    if (actionType.value === 'shell') {
      cfg.command = command.value
      if (cwd.value) cfg.cwd = cwd.value
    } else if (actionType.value === 'script') {
      cfg.language = language.value
      cfg.script = command.value
    } else if (actionType.value === 'http') {
      cfg.url = command.value
      cfg.method = language.value
    }
    cfg.retries = retries.value
  }
  emit('update', { ...props.node, title: title.value, config: cfg })
  emit('close')
}
</script>

<style scoped>
.wf-edit-card {
  position: fixed;
  z-index: var(--z-popover, 60);
  width: 320px;
  max-height: 460px;
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
.wf-edit-card :deep(.field input),
.wf-edit-card :deep(.field textarea) {
  width: 100%;
  background: var(--theme-main-subtle-background);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius-sm, 6px);
  color: inherit;
  padding: 6px 8px;
  font-size: 12px;
}
.wf-edit-card :deep(.field textarea) { min-height: 60px; resize: vertical; font-family: var(--font-mono, monospace); }
.wf-edit-card :deep(.toggle-line) { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.wf-edit-card :deep(.settings-advanced) { border-top: 1px solid var(--theme-main-border); padding-top: 8px; }
.wf-edit-card :deep(.settings-advanced summary) { font-size: 11px; opacity: 0.65; cursor: pointer; }

.wf-tool-checklist {
  max-height: 168px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 3px;
  border-radius: 7px;
  background: var(--theme-main-subtle-background);
}
.wf-tool-check {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 4px 7px;
  border-radius: 5px;
  font-size: 12px;
  cursor: pointer;
  line-height: 1.3;
}
.wf-tool-check:hover { background: var(--theme-main-soft-background); }
/* Small, restrained checkbox — the tool name is the focus, not the box. */
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
