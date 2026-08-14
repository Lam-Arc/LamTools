<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import type { CoreArrangeJob } from '../durable/types'
import { listArrangeJobs, createArrangeJob, updateArrangeJob, renameArrangeJob, editArrangeJob as editArrangeJobApi, listArrangeOccurrences } from '../durable/api'
import { CoreAppServerClient, appServerUrl } from '../appServer'
import UiSelect from './UiSelect.vue'

const props = defineProps<{ workRoot?: string }>()
const emit = defineEmits<{ back: [] }>()

const jobs = ref<CoreArrangeJob[]>([])
const loading = ref(false)
const error = ref('')
const busyIds = ref(new Set<string>())
const terminal = new Set(['cancelled', 'completed'])
const showTerminal = ref(false)

/* ---- inline editing state ---- */
const editingTitle = ref<Record<string, string>>({})
const editingInstruction = ref<Record<string, string>>({})
const expandedHistory = ref(new Set<string>())
const expandedError = ref(new Set<string>())
const occurrences = ref<Record<string, Array<{ id: string; status: string; scheduled_at: string; started_at?: string | null; completed_at?: string | null; attempt_count: number; last_error?: string }>>>({})

/* ---- create / edit form ---- */
const showForm = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const editingJobId = ref<string | null>(null)
const formInstruction = ref('')
const formTitle = ref('')
const formKind = ref('routine')
const formSessionStrategy = ref('new')
const formModelId = ref('')
const formScheduleType = ref<'once' | 'daily' | 'monthly' | 'interval' | 'event'>('once')
const formTimezone = ref('Asia/Shanghai')
const formDate = ref('')
const formTime = ref('09:00')
const formDay = ref(1)
const formEverySeconds = ref(3600)
const formEventType = ref('')
const formMaxRuns = ref<number | undefined>(undefined)
const formSubmitting = ref(false)
const formWorkRoot = ref('')
const formThreadId = ref('')
const availableModels = ref<Array<{ id: string; display_name: string }>>([])
const availableSessions = ref<Array<{ id: string; title: string }>>([])
const availableProjects = ref<Array<{ id: string; name: string; work_root: string }>>([])
const loadingSessions = ref(false)

/* ---- UiSelect option lists ---- */
const kindOptions = [
  { value: 'routine', label: 'routine · 常规' },
  { value: 'focus', label: 'focus · 专注' },
]
const sessionStrategyOptions = [
  { value: 'new', label: '每次新建' },
  { value: 'fixed', label: '固定会话' },
]
const scheduleTypeOptions = [
  { value: 'once', label: '单次' },
  { value: 'daily', label: '每天' },
  { value: 'monthly', label: '每月' },
  { value: 'interval', label: '间隔' },
  { value: 'event', label: '事件' },
]
const modelOptions = computed(() => [
  { value: '', label: '跟随默认' },
  ...availableModels.value.map(m => ({ value: m.id, label: m.display_name })),
])
const threadOptions = computed(() => [
  { value: '', label: loadingSessions.value ? '加载中…' : '-- 选择会话 --' },
  ...availableSessions.value.map(s => ({ value: s.id, label: s.title || s.id.slice(0, 8) })),
])

let _configClient: CoreAppServerClient | null = null
async function configRequest(method: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
  if (!_configClient) {
    const client = new CoreAppServerClient({
      // '' resolves to __LAMTOOLS_API_BASE__ (direct backend) in the desktop
      // app; in browser dev it falls back to the vite origin (proxied). Using
      // window.location.origin here forced the desktop app through the vite
      // proxy to the dead 5172 port — the arrange dialog never worked there.
      url: appServerUrl('', { path: '/api/core/app-server' }),
      clientInfo: { name: 'lamtools_arrange', title: 'Arrange', version: '0.1.0' },
      onConnectionState: (state) => { if (state === 'closed' || state === 'error') _configClient = null },
    })
    await client.connect()
    _configClient = client
  }
  return await _configClient.request(method, params)
}

async function loadProjects() {
  if (availableProjects.value.length > 0) return
  try {
    const result = await configRequest('project.list') as { projects?: Array<{ id: string; name: string; work_root: string }> }
    availableProjects.value = result.projects || []
  } catch (e) { console.error('loadProjects:', e) }
}

async function loadModels() {
  if (availableModels.value.length > 0) return
  try {
    const result = await configRequest('config.models.list') as { models?: Array<{ id: string; model_id: string; display_name: string; provider_name: string }> }
    availableModels.value = (result.models || []).map(m => {
      const pn = m.provider_name || ''
      const mn = m.model_id || m.display_name
      const name = pn && mn ? `${pn}/${mn}` : (m.display_name || m.model_id)
      return { id: name, display_name: name }
    })
  } catch (e) { console.error('loadModels:', e) }
}

async function loadSessions(workRoot: string) {
  loadingSessions.value = true
  availableSessions.value = []
  try {
    const result = await configRequest('project.list') as { projects?: Array<{ id: string; work_root: string }> }
    const project = (result.projects || []).find(p => p.work_root === workRoot)
    if (project) {
      const sessions = await configRequest('project.sessions.list', { project_id: project.id }) as { sessions?: Array<{ id: string; title: string }> }
      availableSessions.value = sessions.sessions || []
    }
  } catch (e) { console.error('loadSessions:', e) }
  finally { loadingSessions.value = false }
}

watch([formSessionStrategy, formWorkRoot], ([strategy, root]) => {
  if (strategy === 'fixed' && root) loadSessions(root)
})

const activeJobs = computed(() =>
  showTerminal.value
    ? [...jobs.value].sort((a, b) => (terminal.has(a.status) ? 1 : 0) - (terminal.has(b.status) ? 1 : 0) || Date.parse(b.updated_at) - Date.parse(a.updated_at))
    : [...jobs.value].filter(j => !terminal.has(j.status)).sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
)

function openCreateForm() {
  formMode.value = 'create'
  editingJobId.value = null
  formInstruction.value = ''
  formTitle.value = ''
  formKind.value = 'routine'
  formSessionStrategy.value = 'new'
  formModelId.value = ''
  formScheduleType.value = 'once'
  formTimezone.value = 'Asia/Shanghai'
  formDate.value = ''
  formTime.value = '09:00'
  formDay.value = 1
  formEverySeconds.value = 3600
  formEventType.value = ''
  formMaxRuns.value = undefined
  formWorkRoot.value = props.workRoot || ''
  formThreadId.value = ''
  showForm.value = true
  loadProjects()
  loadModels()
}

function openEditForm(job: CoreArrangeJob) {
  formMode.value = 'edit'
  editingJobId.value = job.id
  formInstruction.value = instruction(job)
  formTitle.value = job.title || ''
  formKind.value = (job.kind as 'focus' | 'routine') || 'routine'
  formSessionStrategy.value = (job.session_strategy as 'fixed' | 'new') || 'new'
  formModelId.value = job.model_id || ''

  const trigger = job.trigger || {}
  if (trigger.type === 'calendar') {
    if (trigger.frequency === 'daily') {
      formScheduleType.value = 'daily'
      formTime.value = typeof trigger.time === 'string' ? trigger.time : '09:00'
    } else {
      formScheduleType.value = 'monthly'
      formDay.value = typeof trigger.day === 'number' ? trigger.day : 1
      formTime.value = typeof trigger.time === 'string' ? trigger.time : '09:00'
    }
    formTimezone.value = typeof trigger.timezone === 'string' ? trigger.timezone : 'Asia/Shanghai'
  } else if (trigger.type === 'once') {
    formScheduleType.value = 'once'
  } else if (trigger.type === 'interval') {
    formScheduleType.value = 'interval'
    formEverySeconds.value = typeof trigger.every_seconds === 'number' ? trigger.every_seconds : 3600
  } else if (trigger.type === 'event') {
    formScheduleType.value = 'event'
    formEventType.value = typeof trigger.event_type === 'string' ? trigger.event_type : ''
  } else {
    formScheduleType.value = 'once'
  }
  formWorkRoot.value = (job as any).work_root || props.workRoot || ''
  formThreadId.value = job.thread_id || ''
  showForm.value = true
  loadProjects()
  loadModels()
  if (formSessionStrategy.value === 'fixed') loadSessions(formWorkRoot.value)
}

function closeForm() {
  showForm.value = false
  availableSessions.value = []
}

function buildTrigger(): Record<string, unknown> {
  switch (formScheduleType.value) {
    case 'once':
      // Backend (runtime/arrange.py _normalize_trigger) parses once triggers
      // from date/time/timezone; the old local_at-only payload always fell
      // into the date branch with an empty date and failed (audit 18 S2).
      return {
        type: 'once',
        date: formDate.value,
        time: formTime.value ? `${formTime.value}:00` : '',
        timezone: formTimezone.value,
      }
    case 'daily':
      return {
        type: 'calendar',
        frequency: 'daily',
        time: formTime.value,
        timezone: formTimezone.value,
      }
    case 'monthly':
      return {
        type: 'calendar',
        frequency: 'monthly',
        day: formDay.value,
        time: formTime.value,
        timezone: formTimezone.value,
      }
    case 'interval':
      return {
        type: 'interval',
        every_seconds: formEverySeconds.value,
      }
    case 'event':
      return {
        type: 'event',
        event_type: formEventType.value,
      }
    default:
      return { type: 'once' }
  }
}

async function submitForm() {
  if (!formInstruction.value.trim()) return
  formSubmitting.value = true
  error.value = ''
  try {
    if (formMode.value === 'create') {
      await createArrangeJob({
        thread_id: formThreadId.value || '',
        work_root: formWorkRoot.value.trim() || '',
        kind: formKind.value,
        operation: 'turn.start',
        payload: { message: formInstruction.value.trim() },
        trigger: buildTrigger(),
        title: formTitle.value.trim() || undefined,
        session_strategy: formSessionStrategy.value,
        model_id: formModelId.value || undefined,
        max_runs: formMaxRuns.value,
      })
    } else if (editingJobId.value) {
      const fields: Record<string, unknown> = {}
      if (formTitle.value.trim()) fields.title = formTitle.value.trim()
      fields.instruction = formInstruction.value.trim()
      fields.trigger = buildTrigger()
      fields.session_strategy = formSessionStrategy.value
      fields.model_id = formModelId.value || undefined
      await editArrangeJobApi(editingJobId.value, fields as { instruction?: string; trigger?: Record<string, unknown>; session_strategy?: 'fixed' | 'new'; model_id?: string })
    }
    showForm.value = false
    await loadJobs()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '操作失败'
  } finally {
    formSubmitting.value = false
  }
}

async function loadJobs() {
  loading.value = true
  error.value = ''
  try { jobs.value = await listArrangeJobs() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '读取安排失败' }
  finally { loading.value = false }
}

async function changeStatus(job: CoreArrangeJob, action: 'pause' | 'resume' | 'cancel') {
  busyIds.value = new Set([...busyIds.value, job.id])
  error.value = ''
  try {
    const updated = await updateArrangeJob(job.id, action)
    jobs.value = jobs.value.map(item => item.id === updated.id ? updated : item)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '更新安排失败'
  } finally {
    const next = new Set(busyIds.value)
    next.delete(job.id)
    busyIds.value = next
  }
}

/* ---- title inline edit ---- */
function startEditTitle(job: CoreArrangeJob) {
  editingTitle.value = { ...editingTitle.value, [job.id]: job.title || instruction(job) }
}
function cancelEditTitle(jobId: string) {
  const next = { ...editingTitle.value }
  delete next[jobId]
  editingTitle.value = next
}
async function commitTitle(job: CoreArrangeJob) {
  const draft = (editingTitle.value[job.id] || '').trim()
  if (!draft || draft === (job.title || instruction(job))) {
    cancelEditTitle(job.id)
    return
  }
  busyIds.value = new Set([...busyIds.value, job.id])
  try {
    const updated = await renameArrangeJob(job.id, draft)
    jobs.value = jobs.value.map(item => item.id === updated.id ? updated : item)
  } catch { /* keep old title */ }
  finally {
    const next = new Set(busyIds.value)
    next.delete(job.id)
    busyIds.value = next
    cancelEditTitle(job.id)
  }
}

/* ---- instruction inline edit ---- */
function startEditInstruction(job: CoreArrangeJob) {
  editingInstruction.value = { ...editingInstruction.value, [job.id]: instruction(job) }
}
function cancelEditInstruction(jobId: string) {
  const next = { ...editingInstruction.value }
  delete next[jobId]
  editingInstruction.value = next
}
async function commitInstruction(job: CoreArrangeJob) {
  const draft = (editingInstruction.value[job.id] || '').trim()
  if (!draft || draft === instruction(job)) {
    cancelEditInstruction(job.id)
    return
  }
  busyIds.value = new Set([...busyIds.value, job.id])
  try {
    const updated = await editArrangeJobApi(job.id, { instruction: draft })
    jobs.value = jobs.value.map(item => item.id === updated.id ? updated : item)
  } catch { /* keep old */ }
  finally {
    const next = new Set(busyIds.value)
    next.delete(job.id)
    busyIds.value = next
    cancelEditInstruction(job.id)
  }
}

/* ---- session strategy toggle ---- */
async function toggleSessionStrategy(job: CoreArrangeJob) {
  const next = job.session_strategy === 'fixed' ? 'new' : 'fixed'
  busyIds.value = new Set([...busyIds.value, job.id])
  try {
    const updated = await editArrangeJobApi(job.id, { session_strategy: next })
    jobs.value = jobs.value.map(item => item.id === updated.id ? updated : item)
  } catch { /* keep old */ }
  finally {
    const nextIds = new Set(busyIds.value)
    nextIds.delete(job.id)
    busyIds.value = nextIds
  }
}

/* ---- occurrences ---- */
async function toggleHistory(jobId: string) {
  if (expandedHistory.value.has(jobId)) {
    expandedHistory.value = new Set([...expandedHistory.value].filter(id => id !== jobId))
    return
  }
  if (!occurrences.value[jobId]) {
    occurrences.value = { ...occurrences.value, [jobId]: [] }
  }
  expandedHistory.value = new Set([...expandedHistory.value, jobId])
  if (occurrences.value[jobId].length === 0) {
    try {
      const items = await listArrangeOccurrences(jobId)
      occurrences.value = { ...occurrences.value, [jobId]: items }
    } catch { /* ignore */ }
  }
}

function toggleError(jobId: string) {
  if (expandedError.value.has(jobId)) {
    expandedError.value = new Set([...expandedError.value].filter(id => id !== jobId))
  } else {
    expandedError.value = new Set([...expandedError.value, jobId])
  }
}

/* ---- helpers ---- */
function instruction(job: CoreArrangeJob) { return String(job.payload.message || '未命名安排') }
function displayTitle(job: CoreArrangeJob) { return job.title || instruction(job) }
function formatTime(value: string) {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString() : value || '待定'
}
function schedule(job: CoreArrangeJob) {
  const trigger = job.trigger
  if (trigger.type === 'calendar') {
    return trigger.frequency === 'daily'
      ? `每天 ${trigger.time}`
      : `每月 ${trigger.day} 日 ${trigger.time}`
  }
  if (trigger.type === 'once') return `单次 · ${formatTime(String(trigger.local_at || trigger.run_at || job.next_run_at || ''))}`
  if (trigger.type === 'interval') return `每 ${trigger.every_seconds} 秒`
  if (trigger.type === 'event') return `事件 · ${String(trigger.event_type || '')}`
  return '未知触发方式'
}
function statusLabel(status: CoreArrangeJob['status']) {
  return ({ scheduled: '已安排', waiting: '等待事件', running: '运行中', paused: '已暂停', completed: '已完成', failed: '失败', cancelled: '已取消' } as Record<string, string>)[status] || status
}
function statusDot(status: CoreArrangeJob['status']) {
  const t = 'var(--theme-main-text, #fff)'
  if (status === 'running') return t
  if (status === 'failed') return `color-mix(in srgb, ${t} 30%, var(--red) 70%)`
  if (status === 'paused' || status === 'waiting') return `color-mix(in srgb, ${t} 30%, var(--orange) 70%)`
  if (status === 'completed') return t
  return `color-mix(in srgb, ${t} 40%, transparent)`
}
function scheduleLabel(type: string) {
  return ({ once: '单次', daily: '每天', monthly: '每月', interval: '间隔', event: '事件' } as Record<string, string>)[type] || type
}

/* ---- keyboard for inline editors ---- */
function onTitleKeydown(e: KeyboardEvent, job: CoreArrangeJob) {
  if (e.key === 'Enter') { e.preventDefault(); commitTitle(job) }
  else if (e.key === 'Escape') cancelEditTitle(job.id)
}
function onInstructionKeydown(e: KeyboardEvent, job: CoreArrangeJob) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); commitInstruction(job) }
  else if (e.key === 'Escape') cancelEditInstruction(job.id)
}

onMounted(loadJobs)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (showForm.value) { closeForm(); return }
    emit('back')
  }
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport defer to=".workspace-shell">
    <div class="arrange-overlay" @click.self="$emit('back')">
      <div class="arrange-dialog">
        <button class="arrange-card-close" type="button" aria-label="关闭安排" title="关闭安排" @click="$emit('back')">
          <X :size="15" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <main class="arrange-page" :aria-busy="loading">
          <header class="arrange-header">
            <div>
              <h1 class="arrange-title">安排</h1>
              <p class="arrange-subtitle">长期任务，按计划自动执行。</p>
            </div>
      <div class="header-actions">
        <button class="primary-button" @click="openCreateForm">＋ 新建安排</button>
        <button class="quiet-button" :disabled="loading" @click="loadJobs">{{ loading ? '刷新中…' : '刷新' }}</button>
      </div>
    </header>

    <p v-if="loading" class="arrange-loading" role="status">正在读取安排…</p>

    <div v-else-if="error && !showForm" class="arrange-error" role="alert">
      <span>{{ error }}</span>
      <button type="button" @click="loadJobs">重试</button>
    </div>

    <!-- create / edit form -->
    <div v-if="showForm" class="form-card">
      <div class="form-header">
        <strong>{{ formMode === 'create' ? '新建安排' : '编辑安排' }}</strong>
        <button class="text-button" @click="closeForm">取消</button>
      </div>
      <div class="form-body">
        <label class="form-field">
          <span>指令 <em>必填</em></span>
          <textarea v-model="formInstruction" rows="3" placeholder="任务触发时发送给 Agent 的指令…" />
        </label>
        <label class="form-field">
          <span>项目目录 <em>必填</em></span>
          <input
            v-model="formWorkRoot"
            placeholder="E:\Projects\..."
            :list="'project-datalist-' + (editingJobId || 'new')"
          />
          <datalist :id="'project-datalist-' + (editingJobId || 'new')">
            <option v-for="p in availableProjects" :key="p.id" :value="p.work_root">{{ p.name }} · {{ p.work_root }}</option>
          </datalist>
        </label>
        <label class="form-field">
          <span>标题 <em>可选</em></span>
          <input v-model="formTitle" placeholder="留空则自动生成" />
        </label>
        <div class="form-row">
          <label class="form-field">
            <span>类型</span>
            <UiSelect :model-value="formKind" :options="kindOptions" aria-label="类型" @update:model-value="formKind = $event" />
          </label>
          <label class="form-field">
            <span>会话策略</span>
            <UiSelect :model-value="formSessionStrategy" :options="sessionStrategyOptions" aria-label="会话策略" @update:model-value="formSessionStrategy = $event" />
          </label>
        </div>
        <label class="form-field">
          <span>模型 <em>可选</em></span>
          <UiSelect :model-value="formModelId" :options="modelOptions" placeholder="跟随默认" aria-label="模型" @update:model-value="formModelId = $event" />
        </label>
        <label v-if="formSessionStrategy === 'fixed'" class="form-field">
          <span>绑定会话</span>
          <UiSelect :model-value="formThreadId" :options="threadOptions" :disabled="loadingSessions" placeholder="-- 选择会话 --" aria-label="绑定会话" @update:model-value="formThreadId = $event" />
        </label>
        <div class="form-row">
          <label class="form-field">
            <span>调度方式</span>
            <UiSelect :model-value="formScheduleType" :options="scheduleTypeOptions" direction="up" aria-label="调度方式" @update:model-value="formScheduleType = $event as 'once' | 'daily' | 'monthly' | 'interval' | 'event'" />
          </label>
          <label v-if="formScheduleType !== 'event' && formScheduleType !== 'interval'" class="form-field">
            <span>时区</span>
            <input v-model="formTimezone" placeholder="Asia/Shanghai" />
          </label>
        </div>
        <div v-if="formScheduleType === 'once'" class="form-row">
          <label class="form-field">
            <span>日期</span>
            <input v-model="formDate" type="date" />
          </label>
          <label class="form-field">
            <span>时间</span>
            <input v-model="formTime" type="time" />
          </label>
        </div>
        <div v-else-if="formScheduleType === 'daily'" class="form-field">
          <label>
            <span>时间</span>
            <input v-model="formTime" type="time" />
          </label>
        </div>
        <div v-else-if="formScheduleType === 'monthly'" class="form-row">
          <label class="form-field">
            <span>日期</span>
            <input v-model.number="formDay" type="number" min="1" max="31" />
          </label>
          <label class="form-field">
            <span>时间</span>
            <input v-model="formTime" type="time" />
          </label>
        </div>
        <div v-else-if="formScheduleType === 'interval'" class="form-field">
          <label>
            <span>间隔秒数</span>
            <input v-model.number="formEverySeconds" type="number" min="1" />
          </label>
        </div>
        <div v-else-if="formScheduleType === 'event'" class="form-field">
          <label>
            <span>事件类型</span>
            <input v-model="formEventType" placeholder="artifact.changed" />
          </label>
        </div>
        <label class="form-field">
          <span>最大运行次数 <em>可选</em></span>
          <input v-model.number="formMaxRuns" type="number" min="1" placeholder="留空不限" />
        </label>
        <div v-if="error" class="form-error">{{ error }}</div>
        <div class="form-actions">
          <button class="primary-button" :disabled="formSubmitting || !formInstruction.trim()" @click="submitForm">
            {{ formSubmitting ? '提交中…' : formMode === 'create' ? '创建' : '保存' }}
          </button>
          <button class="quiet-button" @click="closeForm">取消</button>
        </div>
      </div>
    </div>

    <div v-if="!loading && !showForm && !error && activeJobs.length === 0 && jobs.length === 0" class="arrange-empty">
      还没有安排。点击上方按钮新建，或直接告诉 Agent「安排一下……」。
    </div>

    <!-- terminal toggle -->
    <div v-if="!loading && !showForm && !error && jobs.some(j => terminal.has(j.status))" class="terminal-toggle">
      <button class="text-button" @click="showTerminal = !showTerminal">
        {{ showTerminal ? '隐藏' : '显示' }}已完成/已取消 ({{ jobs.filter(j => terminal.has(j.status)).length }})
      </button>
    </div>

    <div v-if="!loading && !showForm && !error && activeJobs.length > 0" class="card-list" role="list">
      <article
        v-for="job in activeJobs"
        :key="job.id"
        class="arrange-card"
        role="listitem"
      >
        <!-- row 1: title + actions -->
        <div class="card-row title-row">
          <div class="title-area">
            <input
              v-if="editingTitle[job.id] !== undefined"
              v-model="editingTitle[job.id]"
              class="inline-edit title-edit"
              @blur="commitTitle(job)"
              @keydown="onTitleKeydown($event, job)"
            />
            <strong
              v-else
              class="card-title"
              tabindex="0"
              role="button"
              :aria-label="`重命名 ${displayTitle(job)}`"
              @click="startEditTitle(job)"
              @keydown.enter="startEditTitle(job)"
            >{{ displayTitle(job) }}</strong>
          </div>
          <div class="title-actions">
            <button class="action-btn" :disabled="busyIds.has(job.id)" @click="openEditForm(job)">编辑</button>
            <button
              v-if="['scheduled', 'waiting', 'running'].includes(job.status)"
              class="action-btn"
              :disabled="busyIds.has(job.id)"
              @click="changeStatus(job, 'pause')"
            >暂停</button>
            <button
              v-if="job.status === 'paused'"
              class="action-btn"
              :disabled="busyIds.has(job.id)"
              @click="changeStatus(job, 'resume')"
            >恢复</button>
            <button
              v-if="!terminal.has(job.status)"
              class="action-btn danger"
              :disabled="busyIds.has(job.id)"
              @click="changeStatus(job, 'cancel')"
            >取消</button>
          </div>
        </div>

        <!-- row 2: instruction -->
        <div class="card-row instruction-row">
          <template v-if="editingInstruction[job.id] !== undefined">
            <textarea
              v-model="editingInstruction[job.id]"
              class="inline-edit instruction-edit"
              rows="2"
              @keydown="onInstructionKeydown($event, job)"
            />
            <div class="edit-hint">
              <button class="mini-btn" @click="commitInstruction(job)">确认</button>
              <button class="mini-btn" @click="cancelEditInstruction(job.id)">取消</button>
            </div>
          </template>
          <span
            v-else
            class="card-instruction"
            tabindex="0"
            role="button"
            :aria-label="`编辑指令`"
            @click="startEditInstruction(job)"
            @keydown.enter="startEditInstruction(job)"
          >{{ instruction(job) }}</span>
        </div>

        <!-- row 3: project + session -->
        <div class="card-row meta-row">
          <span class="meta-item">项目 <code>{{ (job.work_root || job.project_id || '').slice(0, 8) || '-' }}</code></span>
          <span class="meta-divider">·</span>
          <span class="meta-item">
            <span class="kind-badge" :class="job.kind">{{ job.kind === 'focus' ? '专注' : '常规' }}</span>
          </span>
          <span class="meta-divider">·</span>
          <span
            class="meta-item clickable"
            tabindex="0"
            role="button"
            :aria-label="`切换会话策略，当前${job.session_strategy === 'fixed' ? '固定会话' : '每次新建'}`"
            @click="toggleSessionStrategy(job)"
            @keydown.enter="toggleSessionStrategy(job)"
          >
            会话 {{ job.session_strategy === 'fixed' ? `固定 · ${(job.thread_id || '').slice(0, 8)}` : '每次新建' }}
          </span>
          <template v-if="job.session_strategy === 'new'">
            <span class="meta-divider">·</span>
            <span class="meta-item">模型 {{ (job.model_id || '跟随默认') }}</span>
          </template>
        </div>

        <!-- row 4: trigger + run count -->
        <div class="card-row trigger-row">
          <span class="meta-item">{{ schedule(job) }}</span>
          <span class="meta-divider">·</span>
          <span class="meta-item">已运行 {{ job.run_count }} 次</span>
          <button
            v-if="job.run_count > 0"
            class="expand-toggle"
            :aria-expanded="expandedHistory.has(job.id)"
            @click="toggleHistory(job.id)"
          >{{ expandedHistory.has(job.id) ? '收起' : '展开' }}历史</button>
        </div>

        <!-- expandable: history -->
        <div v-if="expandedHistory.has(job.id)" class="card-expand history-panel">
          <div v-if="!occurrences[job.id]" class="history-loading">读取中…</div>
          <div v-else-if="occurrences[job.id].length === 0" class="history-empty">暂无运行记录</div>
          <div v-else class="history-list">
            <div
              v-for="occ in occurrences[job.id]"
              :key="occ.id"
              class="history-item"
            >
              <span class="history-time">{{ formatTime(occ.scheduled_at) }}</span>
              <span class="history-status" :style="{ color: occ.status === 'completed' ? 'var(--green)' : occ.status === 'failed' ? 'var(--red)' : 'color-mix(in srgb, var(--theme-main-text) 65%, transparent)' }">
                {{ occ.status === 'completed' ? '完成' : occ.status === 'failed' ? '失败' : occ.status }}
              </span>
              <span v-if="occ.attempt_count > 1" class="history-attempts">×{{ occ.attempt_count }}</span>
            </div>
          </div>
        </div>

        <!-- row 5: status + error -->
        <div class="card-row status-row">
          <span class="status-label" :style="{ color: statusDot(job.status) }">
            <span class="status-dot" :style="{ background: statusDot(job.status) }"></span>
            {{ statusLabel(job.status) }}
          </span>
          <button
            v-if="job.last_error"
            class="error-toggle"
            @click="toggleError(job.id)"
          >{{ expandedError.has(job.id) ? '收起' : '查看' }}错误</button>
        </div>

        <!-- expandable: error -->
        <div v-if="expandedError.has(job.id) && job.last_error" class="card-expand error-panel">
          {{ job.last_error }}
        </div>
      </article>
    </div>
      </main>
    </div>
  </div>
  </Teleport>
</template>

<style scoped>
/* ── Overlay + card ── */
.arrange-overlay {
  position: fixed;
  inset: var(--titlebar-offset, 36px) 0 0 0;
  z-index: var(--z-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
}

.arrange-dialog {
  position: relative;
  width: min(860px, calc(100vw - 48px));
  max-height: calc(100dvh - var(--titlebar-offset, 36px) - 48px);
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 12%, transparent);
  border-radius: var(--radius-lg);
  background: var(--theme-main-background, var(--bg, #111111));
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.arrange-card-close {
  position: absolute;
  top: 12px;
  right: 14px;
  z-index: 5;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 8%, transparent);
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}

.arrange-card-close:hover {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 16%, transparent);
  color: var(--theme-main-text, #f2efeb);
}

/* ── Card content ── */
.arrange-page {
  padding: 20px clamp(24px, 6vw, 48px) 36px;
  color: var(--theme-main-text, var(--text));
  background: transparent;
  overflow-y: auto;
}

.arrange-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; max-width: 780px; margin: 0 auto 20px; }
h1 { margin: 0 0 6px; font-size: 30px; letter-spacing: -.025em; }
.arrange-header p, .text-button { color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); }
p { margin: 0; }
button { font: inherit; } .text-button, .quiet-button { border: 0; background: transparent; color: inherit; cursor: pointer; }
.text-button { padding: 0; } .quiet-button { padding: 7px 12px; border: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 10%, transparent); border-radius: var(--radius-sm); }
.primary-button { padding: 7px 16px; border: 0; border-radius: var(--radius-sm); background: var(--theme-control-background, var(--blue)); color: var(--theme-control-text, #fff); cursor: pointer; font-weight: 600; }
.primary-button:disabled { opacity: .5; cursor: default; }
.header-actions { display: flex; gap: 8px; align-items: center; }

.arrange-loading, .arrange-empty { max-width: 780px; margin-inline: auto; padding: 28px 0; color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); }
.arrange-error { max-width: 780px; margin-inline: auto; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 0; color: var(--red); }
.arrange-error button { flex: none; min-height: 36px; padding: 6px 11px; border: 1px solid currentColor; border-radius: var(--radius-sm); background: transparent; color: inherit; cursor: pointer; }

/* ---- form ---- */
.form-card { max-width: 780px; margin: 0 auto 28px; padding: 20px; border: 1px solid color-mix(in srgb, var(--blue) 36%, transparent); border-radius: var(--radius); background: var(--theme-main-soft-background, color-mix(in srgb, var(--theme-main-text, var(--text)) 5%, transparent)); }
.form-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.form-body { display: flex; flex-direction: column; gap: 14px; }
.form-field { display: flex; flex-direction: column; gap: 4px; }
.form-field span { font-size: 13px; color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); }
.form-field em { font-style: normal; color: var(--orange); }
.form-field input, .form-field textarea {
  box-sizing: border-box; width: 100%; padding: 7px 10px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 12%, transparent); border-radius: 6px;
  background: var(--theme-main-subtle-background, var(--bg)); color: var(--theme-main-text, var(--text)); font: inherit; font-size: 14px;
}
.form-field :deep(.ui-select-trigger) {
  min-height: 36px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 12%, transparent); border-radius: 6px;
  background: var(--theme-main-subtle-background, var(--bg)); color: var(--theme-main-text, var(--text)); font-size: 14px;
}
.form-field textarea { resize: vertical; min-height: 64px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.form-error { color: var(--red); font-size: 13px; }
.form-actions { display: flex; gap: 8px; margin-top: 4px; }

.terminal-toggle { max-width: 780px; margin: 0 auto 12px; }

/* ---- cards ---- */
.card-list { max-width: 780px; margin-inline: auto; display: grid; gap: 16px; }

.arrange-card {
  padding: 18px 20px;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 10%, transparent);
  border-radius: var(--radius);
  background: var(--theme-main-soft-background, color-mix(in srgb, var(--theme-main-text, var(--text)) 5%, transparent));
}
.card-row { display: flex; align-items: center; gap: 8px; }
.card-row + .card-row { margin-top: 10px; }

/* row 1: title */
.title-row { justify-content: space-between; }
.title-area { min-width: 0; flex: 1; }
.card-title { font-size: 15px; font-weight: 600; cursor: pointer; border-radius: 4px; padding: 1px 4px; margin: -1px -4px; }
.card-title:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) var(--alpha-hover), transparent); }
.card-title:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.title-actions { display: flex; gap: 4px; flex-shrink: 0; }
.action-btn { padding: 4px 8px; border: 0; border-radius: 6px; background: transparent; color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); cursor: pointer; font-size: 13px; }
.action-btn:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) var(--alpha-hover), transparent); color: var(--theme-main-text, var(--text)); }
.action-btn:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.action-btn.danger { color: var(--red); }

/* row 2: instruction */
.instruction-row { flex-wrap: wrap; }
.card-instruction { color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); font-size: 13px; cursor: pointer; border-radius: 4px; padding: 2px 4px; margin: -2px -4px; white-space: pre-wrap; }
.card-instruction:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) var(--alpha-hover), transparent); color: var(--theme-main-text, var(--text)); }
.card-instruction:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

/* row 3+4: meta */
.meta-row, .trigger-row { color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); font-size: 13px; }
.meta-item { display: inline-flex; align-items: center; gap: 4px; }
.meta-item.clickable { cursor: pointer; border-radius: 4px; padding: 1px 4px; margin: -1px -4px; }
.meta-item.clickable:hover { background: color-mix(in srgb, var(--theme-main-text, var(--text)) var(--alpha-hover), transparent); color: var(--theme-main-text, var(--text)); }
.meta-item.clickable:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.meta-item code { font-size: 12px; color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); background: color-mix(in srgb, var(--theme-main-text, var(--text)) 6%, transparent); border-radius: 4px; padding: 1px 5px; }
.meta-divider { color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 45%, transparent); }
.kind-badge { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: color-mix(in srgb, var(--theme-main-text, var(--text)) 8%, transparent); }
.kind-badge.focus { background: color-mix(in srgb, var(--orange) 20%, transparent); color: var(--orange); }

/* row 5: status */
.status-row { justify-content: space-between; }
.status-label { font-size: 13px; display: inline-flex; align-items: center; gap: 5px; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }

/* inline edit */
.inline-edit { box-sizing: border-box; width: 100%; padding: 4px 6px; border: 1px solid var(--blue); border-radius: 6px; background: var(--theme-main-subtle-background, var(--bg)); color: var(--theme-main-text, var(--text)); font: inherit; }
.title-edit { font-size: 15px; font-weight: 600; }
.instruction-edit { resize: vertical; min-height: 48px; font-size: 13px; }
.edit-hint { display: flex; gap: 4px; margin-top: 4px; }
.mini-btn { padding: 3px 8px; border: 0; border-radius: var(--radius-sm); background: var(--theme-control-background, var(--blue)); color: var(--theme-control-text, #fff); cursor: pointer; font-size: 12px; }
.mini-btn:last-child { background: transparent; color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); }
.mini-btn:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

/* expand */
.expand-toggle, .error-toggle { padding: 0; border: 0; background: transparent; color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); cursor: pointer; font-size: 12px; }
.expand-toggle:hover, .error-toggle:hover { color: var(--theme-main-text, var(--text)); }
.card-expand { margin-top: 8px; padding: 10px 12px; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-main-text, var(--text)) 4%, transparent); font-size: 13px; }

.history-panel { max-height: 200px; overflow-y: auto; }
.history-loading, .history-empty { color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); }
.history-item { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
.history-item + .history-item { border-top: 1px solid color-mix(in srgb, var(--theme-main-text, var(--text)) 5%, transparent); }
.history-time { color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); min-width: 140px; font-size: 12px; }
.history-status { font-size: 12px; }
.history-attempts { color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent); font-size: 11px; }

.error-panel { color: var(--red); white-space: pre-wrap; word-break: break-all; font-size: 12px; }

button:disabled { cursor: default; opacity: .5; }

@media (max-width: 700px) {
  .arrange-page { padding: 24px 18px; }
  .arrange-card { padding: 14px 16px; }
  .arrange-dialog {
    width: 100vw;
    max-height: calc(100dvh - var(--titlebar-offset, 36px));
    border-radius: 0;
  }
  .form-card { padding: 14px 16px; }
  .form-row { grid-template-columns: 1fr; }
  .title-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .title-actions { width: 100%; flex-wrap: wrap; }
  .action-btn { min-height: 36px; }
  .text-button, .quiet-button { min-height: 44px; }
  .header-actions { flex-direction: column; align-items: stretch; }
  .arrange-card-close { top: 10px; right: 10px; }
}
</style>