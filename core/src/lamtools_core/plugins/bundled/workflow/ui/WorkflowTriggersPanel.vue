<template>
  <section class="wf-trigger-panel" data-workflow-trigger-panel aria-label="工作流触发器与激活">
    <header class="wf-trigger-head">
      <div>
        <h3>触发器</h3>
        <span>{{ triggers.length }} 个 · 工作流 revision {{ workflowRevisionLabel }}</span>
      </div>
      <div class="wf-trigger-head-actions">
        <button
          type="button"
          class="small-btn quiet"
          data-trigger-refresh
          :disabled="activationsLoading || activationBusy"
          aria-label="刷新激活状态"
          title="刷新激活状态"
          @click="refreshActivations"
        >
          <RefreshCw :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button
          type="button"
          class="small-btn primary"
          data-trigger-add
          :disabled="activationBusy || !workflowDefinition"
          aria-label="新增触发器"
          title="新增触发器"
          @click="addTrigger"
        >
          <Plus :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
    </header>

    <ul v-if="triggers.length" class="wf-trigger-list" aria-label="触发器列表">
      <li v-for="trigger in triggers" :key="trigger.id" class="wf-trigger-row" :class="{ selected: trigger.id === selectedTriggerId }">
        <button
          type="button"
          class="wf-trigger-row-main"
          :data-trigger-id="trigger.id"
          :aria-current="trigger.id === selectedTriggerId ? 'true' : undefined"
          @click="selectTrigger(trigger.id)"
        >
          <span class="wf-trigger-dot" :class="{ enabled: trigger.enabled, active: hasActiveActivation(trigger.id) }" aria-hidden="true"></span>
          <span class="wf-trigger-row-copy">
            <strong>{{ trigger.name || triggerTypeLabel(trigger.type) }}</strong>
            <small>{{ triggerSummary(trigger) }}</small>
          </span>
          <span v-if="activationStatus(trigger.id)" class="wf-trigger-status" :class="`status-${activationStatus(trigger.id)}`">
            {{ activationStatusLabel(activationStatus(trigger.id)) }}
          </span>
        </button>
      </li>
    </ul>
    <p v-else class="wf-trigger-empty">暂无触发器。新增后可配置手动或定时入口。</p>

    <form v-if="draft" class="wf-trigger-editor" data-trigger-editor @submit.prevent="saveDraft">
      <div class="wf-trigger-editor-head">
        <strong>{{ draft.name || triggerTypeLabel(draft.type) }}</strong>
        <button type="button" class="text-btn danger" data-trigger-delete :disabled="activationBusy" @click="deleteTrigger">删除</button>
      </div>

      <div class="wf-trigger-fields wf-trigger-fields-meta">
        <label>
          <span>名称</span>
          <input v-model="draft.name" type="text" placeholder="例如：每日同步" autocomplete="off" />
        </label>
        <label>
          <span>ID</span>
          <input v-model="draft.id" type="text" placeholder="trigger_1" autocomplete="off" />
        </label>
        <label>
          <span>类型</span>
          <UiSelect
            :model-value="draft.type"
            :options="triggerTypeOptions"
            aria-label="触发器类型"
            data-trigger-type
            @update:model-value="changeType"
          />
        </label>
        <label class="wf-trigger-checkbox">
          <span>启用</span>
          <span class="wf-trigger-checkbox-control">
            <input v-model="draft.enabled" type="checkbox" />
            <small>{{ draft.enabled ? '会参与激活' : '停用' }}</small>
          </span>
        </label>
      </div>

      <div v-if="draft.type === 'once'" class="wf-trigger-fields">
        <label class="wf-trigger-field-wide">
          <span>at（ISO 时间）</span>
          <input v-model="draft.at" type="text" placeholder="2026-09-14T09:00:00+08:00" autocomplete="off" />
        </label>
      </div>

      <div v-else-if="draft.type === 'interval'" class="wf-trigger-fields">
        <label>
          <span>每隔（秒）</span>
          <input v-model="draft.every_seconds" type="number" min="0.001" step="any" placeholder="3600" />
        </label>
        <label>
          <span>开始时间（可选）</span>
          <input v-model="draft.start_at" type="text" placeholder="ISO 时间" autocomplete="off" />
        </label>
      </div>

      <div v-else-if="draft.type === 'calendar'" class="wf-trigger-fields">
        <label>
          <span>频率</span>
          <UiSelect :model-value="draft.frequency || 'daily'" :options="calendarFrequencyOptions" aria-label="日历频率" @update:model-value="changeFrequency" />
        </label>
        <label>
          <span>时间</span>
          <input v-model="draft.time" type="time" placeholder="09:00" />
        </label>
        <label>
          <span>时区</span>
          <input v-model="draft.timezone" type="text" placeholder="Asia/Shanghai" autocomplete="off" />
        </label>
        <label v-if="draft.frequency === 'monthly'">
          <span>每月第几天</span>
          <input v-model="draft.day" type="number" min="1" max="31" step="1" placeholder="1" />
        </label>
      </div>

      <div v-else-if="draft.type === 'event'" class="wf-trigger-fields">
        <label class="wf-trigger-field-wide">
          <span>事件类型</span>
          <input v-model="draft.event_type" type="text" placeholder="例如：invoice.created" autocomplete="off" />
        </label>
      </div>

      <div v-if="draft.type !== 'once'" class="wf-trigger-fields">
        <label>
          <span>最大运行次数（可选）</span>
          <input v-model="draft.max_runs" type="number" min="1" step="1" placeholder="不限" />
        </label>
      </div>

      <label class="wf-trigger-inputs">
        <span>运行输入（JSON，可选）</span>
        <AutoTextarea v-model="inputsDraft" :min-rows="2" :max-rows="4" placeholder='{"key": "value"}' />
      </label>

      <p v-if="error" class="wf-trigger-error" role="alert">{{ error }}</p>
      <p v-if="message" class="wf-trigger-message" role="status">{{ message }}</p>
      <div class="wf-trigger-editor-actions">
        <button type="submit" class="small-btn primary" data-trigger-save :disabled="activationBusy">保存触发器</button>
      </div>
    </form>

    <section v-if="selectedTrigger" class="wf-activation-section" aria-label="触发器激活">
      <header class="wf-activation-head">
        <div>
          <h4>激活</h4>
          <span v-if="activationsLoading">正在读取…</span>
          <span v-else>{{ selectedTrigger.type === 'manual' ? '手动触发无需排程' : '激活会固定当前工作流 revision' }}</span>
        </div>
        <span v-if="selectedActivationRows.length" class="wf-activation-count">{{ selectedActivationRows.length }}</span>
      </header>
      <ul v-if="selectedActivationRows.length" class="wf-activation-list">
        <li v-for="activation in selectedActivationRows" :key="activation.id" class="wf-activation-row">
          <div class="wf-activation-copy">
            <strong :class="`status-${activation.status}`">{{ activationStatusLabel(activation.status) }}</strong>
            <span>固定 revision {{ activation.workflow_revision || '—' }}</span>
            <small>下次 {{ formatTimestamp(activation.next_run_at) }} · 运行 {{ activation.run_count }}</small>
            <small v-if="activation.last_error" class="wf-trigger-error">{{ activation.last_error }}</small>
          </div>
          <button
            type="button"
            class="text-btn danger"
            data-trigger-deactivate
            :data-activation-id="activation.id"
            :disabled="activationBusy"
            @click="deactivateTrigger"
          >停用</button>
        </li>
      </ul>
      <p v-else class="wf-activation-empty">未激活</p>
      <div v-if="selectedTrigger.type !== 'manual'" class="wf-activation-actions">
        <button
          type="button"
          class="small-btn primary"
          data-trigger-activate
          :disabled="activationBusy || !selectedTrigger.enabled"
          @click="activateTrigger(false)"
        >激活</button>
        <button
          v-if="selectedActivationRows.length"
          type="button"
          class="small-btn quiet"
          data-trigger-replace
          :disabled="activationBusy || !selectedTrigger.enabled"
          title="显式替换现有激活，并固定到当前 revision"
          @click="activateTrigger(true)"
        >替换并激活</button>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Plus, RefreshCw } from 'lucide-vue-next'
import UiSelect from '../../../../../../ui/src/components/UiSelect.vue'
import AutoTextarea from '../../../../../../ui/src/components/AutoTextarea.vue'
import type { WorkflowActivation, WorkflowDef, WorkflowTrigger } from './types'

type TriggerType = WorkflowTrigger['type']
type TriggerDraft = WorkflowTrigger & {
  at?: string
  every_seconds?: number | string
  start_at?: string
  frequency?: 'daily' | 'monthly'
  time?: string
  timezone?: string
  day?: number | string
  event_type?: string
}

const props = withDefaults(defineProps<{
  workflowDefinition?: WorkflowDef | null
  activations?: WorkflowActivation[]
  activationsLoading?: boolean
  activationBusy?: boolean
  onUpdateDefinition?: (definition: WorkflowDef) => void | Promise<void>
  onRefreshActivations?: () => void | Promise<void>
  onActivate?: (triggerId: string, replace: boolean) => void | Promise<void>
  onDeactivate?: (triggerId: string) => void | Promise<void>
}>(), {
  workflowDefinition: null,
  activations: () => [],
  activationsLoading: false,
  activationBusy: false,
  onUpdateDefinition: undefined,
  onRefreshActivations: undefined,
  onActivate: undefined,
  onDeactivate: undefined,
})

const triggerTypeOptions = [
  { value: 'manual', label: '手动' },
  { value: 'once', label: '一次性' },
  { value: 'interval', label: '间隔' },
  { value: 'calendar', label: '日历' },
  { value: 'event', label: '事件' },
]
const calendarFrequencyOptions = [
  { value: 'daily', label: '每天' },
  { value: 'monthly', label: '每月' },
]

const selectedTriggerId = ref('')
const draft = ref<TriggerDraft | null>(null)
const inputsDraft = ref('')
const error = ref('')
const message = ref('')

const triggers = computed<WorkflowTrigger[]>(() => (
  Array.isArray(props.workflowDefinition?.triggers) ? props.workflowDefinition.triggers : []
))
const selectedTrigger = computed(() => triggers.value.find((trigger) => trigger.id === selectedTriggerId.value) || null)
const selectedActivationRows = computed(() => (
  selectedTrigger.value
    ? props.activations.filter((activation) => activation.trigger_id === selectedTrigger.value?.id)
    : []
))
const workflowRevisionLabel = computed(() => String(props.workflowDefinition?.revision ?? '—'))

function clone<T>(value: T): T {
  try { return JSON.parse(JSON.stringify(value)) as T } catch { return value }
}

function syncDraft(): void {
  const available = triggers.value
  if (!available.length) {
    selectedTriggerId.value = ''
    draft.value = null
    inputsDraft.value = ''
    return
  }
  const selected = available.find((trigger) => trigger.id === selectedTriggerId.value) || available[0]
  selectedTriggerId.value = selected.id
  draft.value = clone(selected) as TriggerDraft
  inputsDraft.value = formatInputs(selected.inputs)
  error.value = ''
  message.value = ''
}

watch(() => `${props.workflowDefinition?.id || ''}:${JSON.stringify(props.workflowDefinition?.triggers || [])}`, syncDraft, { immediate: true })

function formatInputs(value: Record<string, unknown> | undefined): string {
  if (!value || !Object.keys(value).length) return ''
  try { return JSON.stringify(value, null, 2) || '' } catch { return '' }
}

function triggerTypeLabel(type: TriggerType | string): string {
  return ({ manual: '手动触发', once: '一次性触发', interval: '间隔触发', calendar: '日历触发', event: '事件触发' } as Record<string, string>)[type] || type
}

function triggerSummary(trigger: WorkflowTrigger): string {
  const raw = trigger as WorkflowTrigger & Record<string, unknown>
  if (trigger.type === 'once') return String(raw.at || '未设置时间')
  if (trigger.type === 'interval') return `每 ${raw.every_seconds || '—'} 秒`
  if (trigger.type === 'calendar') return `${raw.frequency === 'monthly' ? '每月' : '每天'} ${raw.time || '—'} ${raw.timezone || ''}`.trim()
  if (trigger.type === 'event') return String(raw.event_type || '未设置事件')
  return trigger.enabled ? '手动运行' : '已停用'
}

function selectTrigger(id: string): void {
  if (id === selectedTriggerId.value) return
  selectedTriggerId.value = id
  syncDraft()
}

function addTrigger(): void {
  const definition = props.workflowDefinition
  if (!definition) return
  const existing = new Set(triggers.value.map((trigger) => trigger.id))
  let serial = triggers.value.length + 1
  let id = `trigger_${serial}`
  while (existing.has(id)) id = `trigger_${++serial}`
  const trigger: WorkflowTrigger = { id, type: 'manual', enabled: true, name: `触发器 ${serial}`, inputs: {} }
  const next = [...triggers.value, trigger]
  props.onUpdateDefinition?.({ ...definition, triggers: next })
  selectedTriggerId.value = id
  syncDraft()
  message.value = '已新增触发器，请填写配置后保存。'
}

function changeType(value: string): void {
  if (!draft.value) return
  const type = value as TriggerType
  draft.value = { ...draft.value, type }
  if (type === 'interval' && draft.value.every_seconds === undefined) draft.value.every_seconds = 3600
  if (type === 'calendar') {
    draft.value.frequency = draft.value.frequency === 'monthly' ? 'monthly' : 'daily'
    draft.value.time = draft.value.time || '09:00'
    draft.value.timezone = draft.value.timezone || 'Asia/Shanghai'
  }
  if (type === 'event') draft.value.event_type = draft.value.event_type || ''
  error.value = ''
}

function changeFrequency(value: string): void {
  if (!draft.value) return
  draft.value.frequency = value === 'monthly' ? 'monthly' : 'daily'
  if (draft.value.frequency === 'monthly' && draft.value.day === undefined) draft.value.day = 1
}

function parsePositiveNumber(value: unknown, label: string): number | undefined {
  if (value === undefined || value === null || String(value).trim() === '') return undefined
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    error.value = `${label}必须是正数`
    return undefined
  }
  return parsed
}

function buildCanonicalDraft(): WorkflowTrigger | null {
  const value = draft.value
  if (!value) return null
  const id = String(value.id || '').trim()
  if (!id) { error.value = '触发器 ID 不能为空'; return null }
  if (triggers.value.some((trigger) => trigger.id === id && trigger.id !== selectedTriggerId.value)) {
    error.value = `触发器 ID 已存在：${id}`
    return null
  }
  let inputs: Record<string, unknown> = {}
  if (inputsDraft.value.trim()) {
    try {
      const parsed = JSON.parse(inputsDraft.value)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('object')
      inputs = parsed as Record<string, unknown>
    } catch {
      error.value = '运行输入必须是 JSON 对象'
      return null
    }
  }
  const base: WorkflowTrigger = {
    id,
    type: value.type,
    enabled: value.enabled !== false,
    ...(String(value.name || '').trim() ? { name: String(value.name).trim() } : {}),
    inputs,
  }
  if (value.type === 'once') {
    const at = String(value.at || '').trim()
    if (!at) { error.value = '一次性触发器需要 at 时间'; return null }
    return { ...base, at, max_runs: 1 }
  }
  const maxRuns = parsePositiveNumber(value.max_runs, '最大运行次数')
  if (error.value) return null
  if (maxRuns !== undefined) base.max_runs = Math.floor(maxRuns)
  if (value.type === 'interval') {
    const everySeconds = parsePositiveNumber(value.every_seconds, '间隔秒数')
    if (everySeconds === undefined) { if (!error.value) error.value = '间隔触发器需要 every_seconds'; return null }
    base.every_seconds = everySeconds
    const startAt = String(value.start_at || '').trim()
    if (startAt) base.start_at = startAt
  } else if (value.type === 'calendar') {
    const frequency = value.frequency === 'monthly' ? 'monthly' : 'daily'
    const time = String(value.time || '').trim()
    if (!time) { error.value = '日历触发器需要时间'; return null }
    base.frequency = frequency
    base.time = time
    base.timezone = String(value.timezone || 'Asia/Shanghai').trim() || 'Asia/Shanghai'
    if (frequency === 'monthly') {
      const day = Number(value.day)
      if (!Number.isInteger(day) || day < 1 || day > 31) { error.value = '每月日期必须是 1 到 31'; return null }
      base.day = day
    }
  } else if (value.type === 'event') {
    const eventType = String(value.event_type || '').trim()
    if (!eventType) { error.value = '事件触发器需要 event_type'; return null }
    base.event_type = eventType
  }
  return base
}

function saveDraft(): void {
  const definition = props.workflowDefinition
  error.value = ''
  message.value = ''
  const canonical = buildCanonicalDraft()
  if (!definition || !canonical) return
  const next = triggers.value.map((trigger) => trigger.id === selectedTriggerId.value ? canonical : trigger)
  props.onUpdateDefinition?.({ ...definition, triggers: next })
  selectedTriggerId.value = canonical.id
  draft.value = clone(canonical) as TriggerDraft
  inputsDraft.value = formatInputs(canonical.inputs)
  message.value = '触发器已保存。'
}

function deleteTrigger(): void {
  const definition = props.workflowDefinition
  if (!definition || !selectedTrigger.value) return
  const next = triggers.value.filter((trigger) => trigger.id !== selectedTrigger.value?.id)
  props.onUpdateDefinition?.({ ...definition, triggers: next })
  selectedTriggerId.value = next[0]?.id || ''
  syncDraft()
}

function activationStatus(triggerId: string): string {
  const active = props.activations.find((activation) => activation.trigger_id === triggerId)
  return active?.status || ''
}

function hasActiveActivation(triggerId: string): boolean {
  return props.activations.some((activation) => activation.trigger_id === triggerId && ['scheduled', 'waiting', 'running', 'paused'].includes(activation.status))
}

function activationStatusLabel(status: string): string {
  return ({ scheduled: '已排程', waiting: '等待中', running: '运行中', paused: '已暂停', completed: '已完成', failed: '失败', cancelled: '已停用' } as Record<string, string>)[status] || status || '未知'
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function refreshActivations(): void { void props.onRefreshActivations?.() }

async function activateTrigger(replace: boolean): Promise<void> {
  const trigger = selectedTrigger.value
  if (!trigger || trigger.type === 'manual' || trigger.enabled === false) return
  error.value = ''
  message.value = ''
  try {
    await props.onActivate?.(trigger.id, replace)
    message.value = replace ? '已替换并激活。' : '已激活。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function deactivateTrigger(): Promise<void> {
  const trigger = selectedTrigger.value
  if (!trigger) return
  error.value = ''
  message.value = ''
  try {
    await props.onDeactivate?.(trigger.id)
    message.value = '已停用。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}
</script>

<style scoped>
.wf-trigger-panel {
  --trigger-text: var(--theme-backdrop-text);
  display: grid;
  gap: var(--space-2);
  min-width: 0;
  padding: var(--space-3);
  border-bottom: 1px solid color-mix(in srgb, var(--trigger-text) 10%, transparent);
  color: var(--trigger-text);
}
.wf-trigger-head, .wf-trigger-editor-head, .wf-activation-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.wf-trigger-head h3, .wf-activation-head h4 { margin: 0; font-size: 12px; font-weight: 700; }
.wf-trigger-head span, .wf-activation-head span { display: block; margin-top: 2px; color: color-mix(in srgb, var(--trigger-text) 48%, transparent); font-size: 10px; }
.wf-trigger-head-actions, .wf-trigger-editor-actions, .wf-activation-actions { display: flex; align-items: center; gap: var(--space-1); }
.wf-trigger-panel .small-btn, .wf-trigger-panel .text-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  border: 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 10px;
}
.wf-trigger-panel .small-btn { padding: 0 var(--space-2); background: color-mix(in srgb, var(--theme-control-background) 82%, transparent); color: var(--theme-control-text); }
.wf-trigger-panel .small-btn.primary { background: var(--theme-control-background); color: var(--theme-control-text); font-weight: 650; }
.wf-trigger-panel .small-btn.quiet, .wf-trigger-panel .text-btn { background: transparent; color: color-mix(in srgb, var(--trigger-text) 68%, transparent); }
.wf-trigger-panel .small-btn:hover:not(:disabled), .wf-trigger-panel .text-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--trigger-text) var(--alpha-hover), transparent); color: var(--trigger-text); }
.wf-trigger-panel .small-btn.primary:hover:not(:disabled) { filter: brightness(.94); }
.wf-trigger-panel .text-btn.danger { color: var(--red); }
.wf-trigger-panel .text-btn.danger:hover:not(:disabled) { background: color-mix(in srgb, var(--red) var(--alpha-hover), transparent); }
.wf-trigger-panel button:disabled { cursor: default; opacity: .45; }
.wf-trigger-panel button:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent); outline-offset: 1px; }
.wf-trigger-list, .wf-activation-list { display: grid; gap: var(--space-1); max-height: 156px; margin: 0; padding: 0; overflow: auto; list-style: none; }
.wf-trigger-row { min-width: 0; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--trigger-text) 4%, transparent); }
.wf-trigger-row.selected { background: color-mix(in srgb, var(--blue) 14%, transparent); }
.wf-trigger-row-main { display: flex; align-items: center; gap: var(--space-2); width: 100%; min-width: 0; min-height: 36px; padding: var(--space-1) var(--space-2); border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--trigger-text); text-align: left; cursor: pointer; }
.wf-trigger-row-main:hover { background: color-mix(in srgb, var(--trigger-text) var(--alpha-hover), transparent); }
.wf-trigger-dot { flex: 0 0 auto; width: 7px; height: 7px; border-radius: 50%; background: color-mix(in srgb, var(--trigger-text) 36%, transparent); }
.wf-trigger-dot.enabled { background: var(--orange); }
.wf-trigger-dot.active { background: var(--green); }
.wf-trigger-row-copy { display: grid; min-width: 0; gap: 1px; }
.wf-trigger-row-copy strong, .wf-trigger-row-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wf-trigger-row-copy strong { font-size: 11px; font-weight: 650; }
.wf-trigger-row-copy small { color: color-mix(in srgb, var(--trigger-text) 52%, transparent); font-size: 9px; }
.wf-trigger-status { margin-left: auto; flex: 0 0 auto; font-size: 9px; font-weight: 650; }
.wf-trigger-status.status-scheduled, .wf-trigger-status.status-waiting, .wf-trigger-status.status-paused { color: var(--orange); }
.wf-trigger-status.status-running { color: var(--blue); }
.wf-trigger-status.status-completed { color: var(--green); }
.wf-trigger-status.status-failed { color: var(--red); }
.wf-trigger-empty, .wf-activation-empty { margin: 0; color: color-mix(in srgb, var(--trigger-text) 46%, transparent); font-size: 10px; }
.wf-trigger-editor { display: grid; gap: var(--space-2); padding-top: var(--space-2); border-top: 1px solid color-mix(in srgb, var(--trigger-text) 10%, transparent); }
.wf-trigger-editor-head strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.wf-trigger-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); }
.wf-trigger-fields-meta { grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); }
.wf-trigger-fields label, .wf-trigger-inputs { display: grid; min-width: 0; gap: var(--space-1); }
.wf-trigger-fields label > span, .wf-trigger-inputs > span { color: color-mix(in srgb, var(--trigger-text) 62%, transparent); font-size: 10px; }
.wf-trigger-field-wide { grid-column: 1 / -1; }
.wf-trigger-panel input:not([type='checkbox']):not([type='radio']):not([type='range']):not([type='color']):not([type='file']):not([type='hidden']):not([type='button']):not([type='submit']):not([type='reset']):not([type='image']) { width: 100%; min-width: 0; box-sizing: border-box; min-height: 30px; border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent); color: var(--theme-composer-text); caret-color: var(--theme-composer-text); padding: 0 var(--space-2); font: inherit; font-size: 11px; outline: 0; }
.wf-trigger-panel :deep(.ui-select-trigger) { width: 100%; min-width: 0; box-sizing: border-box; min-height: 30px; border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); padding: 0 var(--space-2); font: inherit; font-size: 11px; outline: 0; }
.wf-trigger-panel :deep(.ui-select-trigger) { padding-right: var(--space-3); }
.wf-trigger-panel input:not([type='checkbox']):not([type='radio']):not([type='range']):not([type='color']):not([type='file']):not([type='hidden']):not([type='button']):not([type='submit']):not([type='reset']):not([type='image']):focus, .wf-trigger-panel :deep(.ui-select-trigger:focus) { outline: none; }
.wf-trigger-checkbox-control { display: flex; align-items: center; gap: var(--space-1); min-height: 30px; color: var(--theme-control-text); }
.wf-trigger-checkbox-control input { width: 14px; min-height: 14px; accent-color: var(--green); }
.wf-trigger-checkbox-control small { color: color-mix(in srgb, var(--trigger-text) 58%, transparent); font-size: 10px; }
.wf-trigger-inputs :deep(.auto-textarea) { min-height: 46px; }
.wf-trigger-error { margin: 0; color: var(--red) !important; font-size: 10px !important; white-space: pre-wrap; word-break: break-word; }
.wf-trigger-message { margin: 0; color: var(--green); font-size: 10px; }
.wf-activation-section { display: grid; gap: var(--space-2); padding-top: var(--space-2); border-top: 1px solid color-mix(in srgb, var(--trigger-text) 10%, transparent); }
.wf-activation-count { min-width: 18px; color: var(--blue) !important; text-align: right; }
.wf-activation-row { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-2); padding: var(--space-1) var(--space-2); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--trigger-text) 4%, transparent); }
.wf-activation-copy { display: grid; min-width: 0; gap: 1px; }
.wf-activation-copy strong { font-size: 10px; }
.wf-activation-copy strong.status-scheduled, .wf-activation-copy strong.status-waiting, .wf-activation-copy strong.status-paused { color: var(--orange); }
.wf-activation-copy strong.status-running { color: var(--blue); }
.wf-activation-copy strong.status-completed { color: var(--green); }
.wf-activation-copy strong.status-failed { color: var(--red); }
.wf-activation-copy span, .wf-activation-copy small { color: color-mix(in srgb, var(--trigger-text) 52%, transparent); font-size: 9px; overflow-wrap: anywhere; }
.wf-activation-actions { justify-content: flex-start; }
@media (max-width: 640px) {
  .wf-trigger-panel .small-btn, .wf-trigger-panel .text-btn, .wf-trigger-row-main { min-height: 44px; }
  .wf-trigger-fields, .wf-trigger-fields-meta { grid-template-columns: minmax(0, 1fr); }
  .wf-trigger-field-wide { grid-column: auto; }
}
@media (prefers-reduced-motion: reduce) {
  .wf-trigger-panel *, .wf-trigger-panel { transition: none; animation: none; }
}
</style>
