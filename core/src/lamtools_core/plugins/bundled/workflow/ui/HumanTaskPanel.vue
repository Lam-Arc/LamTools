<template>
  <section class="wf-human-task-panel" aria-labelledby="wf-human-task-title">
    <header class="wf-human-task-head">
      <div class="wf-human-task-heading">
        <ClipboardList :size="14" :stroke-width="1.8" aria-hidden="true" />
        <h3 id="wf-human-task-title">人工任务</h3>
        <span v-if="tasks.length" class="wf-human-task-count" aria-label="任务数量">{{ tasks.length }}</span>
      </div>
      <button
        type="button"
        class="wf-human-task-icon-btn"
        :disabled="loading || busy"
        aria-label="刷新人工任务"
        title="刷新"
        @click="refresh"
      >
        <RefreshCw :size="13" :stroke-width="1.8" aria-hidden="true" :class="{ 'is-spinning': loading }" />
      </button>
    </header>

    <p v-if="error" class="wf-human-task-error" role="alert">{{ error }}</p>
    <p v-else-if="loading && !tasks.length" class="wf-human-task-empty" aria-live="polite">读取中…</p>
    <p v-else-if="!tasks.length" class="wf-human-task-empty">暂无待处理任务</p>
    <ul v-else class="wf-human-task-list">
      <li v-for="task in tasks" :key="task.task_id" class="wf-human-task-item">
        <button
          type="button"
          class="wf-human-task-row"
          :class="{ 'is-selected': task.task_id === selectedTaskId }"
          :aria-current="task.task_id === selectedTaskId ? 'true' : undefined"
          @click="select(task.task_id)"
        >
          <span class="wf-human-task-state" :class="`status-${task.status}`" aria-hidden="true">●</span>
          <span class="wf-human-task-row-copy">
            <strong>{{ task.title || task.node || '人工任务' }}</strong>
            <small>{{ task.kind === 'approval' ? '审批' : '等待事件' }} · {{ task.event_type || 'event' }}</small>
          </span>
          <span v-if="task.due_at" class="wf-human-task-due">{{ formatDue(task.due_at) }}</span>
        </button>
      </li>
    </ul>

    <div v-if="selectedTask" class="wf-human-task-detail">
      <div class="wf-human-task-detail-head">
        <div>
          <strong>{{ selectedTask.title || selectedTask.node || '人工任务' }}</strong>
          <small>{{ selectedTask.workflow_name || selectedTask.workflow || selectedTask.workflow_id }}</small>
        </div>
        <span class="wf-human-task-detail-status" :class="`status-${selectedTask.status}`">
          {{ statusLabel(selectedTask.status) }}
        </span>
      </div>
      <dl class="wf-human-task-meta">
        <div><dt>事件</dt><dd>{{ selectedTask.event_type || 'event' }}</dd></div>
        <div v-if="selectedTask.assignee"><dt>负责人</dt><dd>{{ selectedTask.assignee }}</dd></div>
        <div v-if="selectedTask.group"><dt>分组</dt><dd>{{ selectedTask.group }}</dd></div>
        <div v-if="selectedTask.due_at"><dt>截止</dt><dd>{{ formatDue(selectedTask.due_at) }}</dd></div>
      </dl>
      <details v-if="hasForm" class="wf-human-task-form-preview">
        <summary>表单说明</summary>
        <pre>{{ formatValue(selectedTask.form) }}</pre>
      </details>
      <template v-if="selectedTask.status === 'pending'">
        <label class="wf-human-task-payload-label" for="wf-human-task-payload">提交数据（JSON）</label>
        <textarea
          id="wf-human-task-payload"
          v-model="payloadText"
          class="wf-human-task-payload"
          rows="2"
          spellcheck="false"
          :disabled="busy"
          placeholder="{}"
        />
        <p v-if="parseError" class="wf-human-task-error" role="alert">{{ parseError }}</p>
        <div class="wf-human-task-actions">
          <button
            v-if="selectedTask.kind === 'approval'"
            type="button"
            class="wf-human-task-action danger"
            :disabled="busy"
            @click="complete('reject')"
          >
            <X :size="13" :stroke-width="2" aria-hidden="true" />拒绝
          </button>
          <button
            type="button"
            class="wf-human-task-action primary"
            :disabled="busy"
            @click="complete(selectedTask.kind === 'approval' ? 'approve' : '')"
          >
            <Check :size="13" :stroke-width="2" aria-hidden="true" />
            {{ busy ? '提交中…' : selectedTask.kind === 'approval' ? '批准' : '提交' }}
          </button>
        </div>
      </template>
      <details v-if="selectedTask.audit?.length" class="wf-human-task-audit">
        <summary>事件审计（{{ selectedTask.audit.length }}）</summary>
        <ul>
          <li v-for="event in selectedTask.audit" :key="event.event_id || `${event.sequence}-${event.kind}`">
            <span>{{ event.kind }}</span><small>{{ formatDue(event.occurred_at) }}</small>
          </li>
        </ul>
      </details>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check, ClipboardList, RefreshCw, X } from 'lucide-vue-next'
import type { WorkflowHumanTask } from './types'

const props = withDefaults(defineProps<{
  tasks?: WorkflowHumanTask[]
  selectedTask?: WorkflowHumanTask | null
  loading?: boolean
  busy?: boolean
  error?: string
  onRefresh?: () => void | Promise<void>
  onSelect?: (taskId: string) => void | Promise<void>
  onComplete?: (task: WorkflowHumanTask, decision: string, payload: Record<string, unknown>) => void | Promise<void>
}>(), {
  tasks: () => [],
  selectedTask: null,
  loading: false,
  busy: false,
  error: '',
  onRefresh: undefined,
  onSelect: undefined,
  onComplete: undefined,
})

const selectedTaskId = ref('')
const payloadText = ref('{}')
const parseError = ref('')
const hasForm = computed(() => props.selectedTask?.form !== undefined && props.selectedTask?.form !== null && formatValue(props.selectedTask.form) !== '{}')

watch(() => props.selectedTask, (task) => {
  selectedTaskId.value = task?.task_id || ''
  parseError.value = ''
  payloadText.value = '{}'
}, { immediate: true })

watch(() => props.tasks, (tasks) => {
  if (selectedTaskId.value && !tasks.some((task) => task.task_id === selectedTaskId.value)) {
    selectedTaskId.value = ''
  }
})

function refresh(): void {
  void props.onRefresh?.()
}

function select(taskId: string): void {
  selectedTaskId.value = taskId
  void props.onSelect?.(taskId)
}

function complete(decision: string): void {
  parseError.value = ''
  let payload: unknown
  try {
    payload = JSON.parse(payloadText.value || '{}')
  } catch {
    parseError.value = '提交数据必须是有效 JSON'
    return
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    parseError.value = '提交数据必须是 JSON 对象'
    return
  }
  const task = props.selectedTask
  if (!task) return
  const value = { task, decision, payload: payload as Record<string, unknown> }
  void props.onComplete?.(task, decision, value.payload)
}

function statusLabel(status: string): string {
  if (status === 'pending') return '待处理'
  if (status === 'completed') return '已完成'
  if (status === 'cancelled') return '已取消'
  if (status === 'failed') return '失败'
  return status || '未知'
}

function formatDue(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function formatValue(value: unknown): string {
  if (value === undefined || value === null) return '{}'
  if (typeof value === 'string') return value || '{}'
  try { return JSON.stringify(value, null, 2) || '{}' } catch { return String(value) }
}
</script>

<style scoped>
.wf-human-task-panel {
  --text: var(--theme-backdrop-text);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-height: 0;
  padding: var(--space-3);
  border-bottom: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
  color: var(--text);
  font-size: 11px;
}
.wf-human-task-head, .wf-human-task-heading, .wf-human-task-detail-head, .wf-human-task-actions { display: flex; align-items: center; }
.wf-human-task-head, .wf-human-task-detail-head { justify-content: space-between; gap: var(--space-2); }
.wf-human-task-heading { gap: var(--space-1); }
.wf-human-task-heading h3 { margin: 0; font-size: 12px; font-weight: 700; }
.wf-human-task-count { min-width: 17px; padding: 1px var(--space-1); border-radius: 999px; background: color-mix(in srgb, var(--orange) 20%, transparent); color: var(--orange); font-size: 10px; text-align: center; }
.wf-human-task-icon-btn, .wf-human-task-action { display: inline-flex; align-items: center; justify-content: center; gap: var(--space-1); border: 0; border-radius: var(--radius-sm); cursor: pointer; }
.wf-human-task-icon-btn { min-width: 26px; min-height: 26px; padding: 0 var(--space-1); background: transparent; color: color-mix(in srgb, var(--text) 68%, transparent); }
.wf-human-task-icon-btn:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.wf-human-task-icon-btn:active { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); }
.wf-human-task-icon-btn:focus-visible, .wf-human-task-action:focus-visible, .wf-human-task-row:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 72%, transparent); outline-offset: 1px; }
.wf-human-task-icon-btn:disabled, .wf-human-task-action:disabled { opacity: .45; cursor: default; }
.wf-human-task-list { display: grid; gap: var(--space-1); max-height: 190px; margin: 0; padding: 0; overflow: auto; list-style: none; }
.wf-human-task-row { display: flex; align-items: center; gap: var(--space-2); width: 100%; min-width: 0; padding: var(--space-1) var(--space-2); border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--text); text-align: left; cursor: pointer; }
.wf-human-task-row:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); }
.wf-human-task-row:active, .wf-human-task-row.is-selected { background: color-mix(in srgb, var(--blue) var(--alpha-active), transparent); }
.wf-human-task-state { flex: 0 0 auto; color: var(--orange); font-size: 10px; }
.wf-human-task-state.status-completed { color: var(--green); }
.wf-human-task-state.status-failed { color: var(--red); }
.wf-human-task-row-copy { display: grid; min-width: 0; gap: 1px; }
.wf-human-task-row-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 650; }
.wf-human-task-row-copy small, .wf-human-task-detail-head small { overflow: hidden; color: color-mix(in srgb, var(--text) 56%, transparent); text-overflow: ellipsis; white-space: nowrap; }
.wf-human-task-due { margin-left: auto; color: color-mix(in srgb, var(--orange) 76%, var(--text)); font-size: 10px; white-space: nowrap; }
.wf-human-task-empty { margin: 0; color: color-mix(in srgb, var(--text) 45%, transparent); }
.wf-human-task-error { margin: 0; color: var(--red); font-size: 10px; }
.wf-human-task-detail { display: grid; gap: var(--space-2); padding-top: var(--space-2); border-top: 1px solid color-mix(in srgb, var(--text) 10%, transparent); }
.wf-human-task-detail-head > div { display: grid; min-width: 0; gap: 1px; }
.wf-human-task-detail-status { flex: 0 0 auto; color: var(--orange); font-size: 10px; font-weight: 650; }
.wf-human-task-detail-status.status-completed { color: var(--green); }
.wf-human-task-detail-status.status-failed { color: var(--red); }
.wf-human-task-meta { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-1) var(--space-2); margin: 0; }
.wf-human-task-meta div { display: grid; min-width: 0; gap: 1px; }
.wf-human-task-meta dt { color: color-mix(in srgb, var(--text) 48%, transparent); font-size: 10px; }
.wf-human-task-meta dd { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wf-human-task-form-preview, .wf-human-task-audit { display: grid; gap: var(--space-1); }
.wf-human-task-form-preview summary, .wf-human-task-audit summary { color: color-mix(in srgb, var(--text) 58%, transparent); cursor: pointer; }
.wf-human-task-form-preview pre { max-height: 100px; margin: 0; padding: var(--space-2); overflow: auto; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-backdrop-background) 82%, transparent); font: 10px/1.35 var(--font-mono, monospace); white-space: pre-wrap; word-break: break-word; }
.wf-human-task-payload-label { color: color-mix(in srgb, var(--text) 58%, transparent); font-size: 10px; }
.wf-human-task-payload { width: 100%; box-sizing: border-box; min-height: 42px; max-height: 110px; padding: var(--space-1) var(--space-2); resize: none; border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); font: 10px/1.4 var(--font-mono, monospace); white-space: pre-wrap; }
.wf-human-task-payload:focus { outline: 0; }
.wf-human-task-actions { justify-content: flex-end; gap: var(--space-2); }
.wf-human-task-action { min-height: 28px; padding: 0 var(--space-2); background: color-mix(in srgb, var(--theme-control-background) 80%, transparent); color: var(--theme-control-text); font-size: 11px; font-weight: 650; }
.wf-human-task-action:hover:not(:disabled) { filter: brightness(.94); }
.wf-human-task-action.danger { background: var(--red); color: var(--theme-control-text); }
.wf-human-task-audit ul { display: grid; gap: var(--space-1); max-height: 100px; margin: 0; padding: 0; overflow: auto; list-style: none; }
.wf-human-task-audit li { display: flex; justify-content: space-between; gap: var(--space-2); color: color-mix(in srgb, var(--text) 72%, transparent); font-size: 10px; }
.wf-human-task-audit small { color: color-mix(in srgb, var(--text) 48%, transparent); }
.is-spinning { animation: wf-human-task-spin .8s linear infinite; }
@keyframes wf-human-task-spin { to { transform: rotate(360deg); } }
@media (max-width: 640px) { .wf-human-task-icon-btn, .wf-human-task-action { min-height: 44px; } }
@media (prefers-reduced-motion: reduce) { .wf-human-task-panel *, .wf-human-task-panel { transition: none; animation: none; } }
</style>
