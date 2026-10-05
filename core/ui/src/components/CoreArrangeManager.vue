<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  ArrowLeft,
  CalendarClock,
  CircleAlert,
  Clock3,
  Plus,
  Radar,
  RotateCw,
  Sunrise,
  Trash2,
  type LucideIcon,
} from 'lucide-vue-next'
import type { CoreArrangeJob } from '../durable/types'
import { createDurableApi, type CoreDurableRequest } from '../durable/api'
import FullAreaActions from './FullAreaActions.vue'
import UiSelect from './UiSelect.vue'

const props = defineProps<{
  workRoot?: string
  requestRpc: CoreDurableRequest
  /** Desktop sends the actions into the header band; phones render them in place. */
  bandActions?: boolean
}>()
const emit = defineEmits<{
  back: []
  /** 顶部条标题跟随内部子页（列表 / 新建 / 编辑）变化。 */
  heading: [payload: { title: string; subtitle: string }]
}>()
const durable = createDurableApi(props.requestRpc)

const jobs = ref<CoreArrangeJob[]>([])
const schedulerNotice = ref('')
const loading = ref(false)
const error = ref('')
const busyIds = ref(new Set<string>())
const terminal = new Set(['cancelled', 'completed'])
const ACTIVE_STATUSES = new Set(['scheduled', 'waiting', 'running', 'paused'])

/* ---- 子页导航：列表 / 新建 / 编辑，顶部条标题随动 ---- */
const view = ref<'list' | 'create' | 'edit'>('list')
const editingJob = ref<CoreArrangeJob | null>(null)

/* ---- 列表：状态筛选 ---- */
type FilterId = 'all' | 'active' | 'completed' | 'failed'
const filter = ref<FilterId>('all')
const filterDefs: Array<{ id: FilterId; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'active', label: '进行中' },
  { id: 'completed', label: '已完成' },
  { id: 'failed', label: '失败' },
]

/* ---- 内置模板：点击带入新建页 ---- */
interface ArrangeTemplate {
  id: string
  icon: LucideIcon
  name: string
  description: string
  scheduleLabel: string
  apply: { title: string; instruction: string; time: string }
}
const templates: ArrangeTemplate[] = [
  {
    id: 'morning-brief',
    icon: Sunrise,
    name: '晨会摘要',
    description: '汇总昨天以来的会话进展、完成事项与待跟进项，生成不超过 6 条的口述摘要。只读分析，不改动文件。',
    scheduleLabel: '每天 09:00',
    apply: {
      title: '晨会摘要',
      instruction: '汇总昨天以来的会话进展、完成事项与待跟进项，生成不超过 6 条的口述摘要；只读分析，不改动任何文件。',
      time: '09:00',
    },
  },
  {
    id: 'risk-scan',
    icon: Radar,
    name: '风险扫描',
    description: '检查最近 24 小时的代码与数据变更，识别运行错误、数据丢失与权限越界等风险，并附代码位置与修复建议。',
    scheduleLabel: '每天 10:00',
    apply: {
      title: '风险扫描',
      instruction: '检查最近 24 小时的代码与数据变更，识别运行错误、数据丢失与权限越界等风险，并附代码位置与修复建议。',
      time: '10:00',
    },
  },
]

/* ---- 表单状态（新建 / 编辑共用） ---- */
const formTab = ref<'settings' | 'history'>('settings')
const formInstruction = ref('')
const formTitle = ref('')
const formSessionKey = ref('') // '' = 每次新建；否则为固定会话 id
const formModelId = ref('')
const formScheduleType = ref<'once' | 'daily' | 'monthly' | 'interval' | 'event'>('once')
const hasSchedule = ref(false)
const formTimezone = ref('Asia/Shanghai')
const formDate = ref('')
const formTime = ref('09:00')
const formDay = ref(1)
const formEverySeconds = ref(3600)
const formEventType = ref('')
const formMaxRuns = ref<number | undefined>(undefined)
const formSubmitting = ref(false)
const formWorkRoot = ref('')
const availableModels = ref<Array<{ id: string; display_name: string }>>([])
const defaultModelId = ref('')
const availableSessions = ref<Array<{ id: string; title: string }>>([])
const availableProjects = ref<Array<{ id: string; name: string; work_root: string }>>([])
const loadingSessions = ref(false)

/* ---- 运行记录 ---- */
const occurrences = ref<Record<string, Array<{ id: string; status: string; scheduled_at: string; started_at?: string | null; completed_at?: string | null; attempt_count: number; last_error?: string }>>>({})
const historyLoading = ref(false)

/* ---- UiSelect 选项 ---- */
const scheduleTypeOptions = [
  { value: 'once', label: '单次' },
  { value: 'daily', label: '每天' },
  { value: 'monthly', label: '每月' },
  { value: 'interval', label: '间隔' },
  { value: 'event', label: '事件' },
]
const modelOptions = computed(() =>
  availableModels.value.map(m => ({ value: m.id, label: m.display_name })),
)
const threadOptions = computed(() => [
  { value: '', label: '每次新建' },
  ...availableSessions.value.map(s => ({ value: s.id, label: s.title || s.id.slice(0, 8) })),
])
const projectOptions = computed(() => {
  const opts = availableProjects.value.map(p => ({ value: p.work_root, label: p.name }))
  if (props.workRoot && !availableProjects.value.some(p => p.work_root === props.workRoot)) {
    opts.unshift({ value: props.workRoot, label: '当前项目' })
  }
  return opts
})

async function loadProjects() {
  if (availableProjects.value.length > 0) return
  try {
    const result = await props.requestRpc('project.list') as { projects?: Array<{ id: string; name: string; work_root: string }> }
    availableProjects.value = result.projects || []
  } catch (e) { console.error('loadProjects:', e) }
}

async function loadModels() {
  if (availableModels.value.length > 0) return
  try {
    const result = await props.requestRpc('config.models.list') as { models?: Array<{ id: string; model_id: string; display_name: string; provider_name: string }>, default_model_id?: string }
    availableModels.value = (result.models || []).map(m => ({
      // 选项值必须是模型记录 id（后端 turn.start 按它解析），显示名另拼。
      id: m.id || m.model_id,
      display_name: [m.provider_name, m.model_id || m.display_name].filter(Boolean).join('/') || m.display_name,
    }))
    defaultModelId.value = String(result.default_model_id || '')
    // 定时任务必须绑定一个具体模型：表单开着还没选时，先带出当前默认模型
    // （即此刻会话在用的模型），用户可再改。
    if (!formModelId.value && view.value !== 'list' && defaultModelId.value) {
      formModelId.value = defaultModelId.value
    }
  } catch (e) { console.error('loadModels:', e) }
}

async function loadSessions(workRoot: string) {
  if (!workRoot) {
    availableSessions.value = []
    return
  }
  loadingSessions.value = true
  try {
    const result = await props.requestRpc('project.list') as { projects?: Array<{ id: string; work_root: string }> }
    const project = (result.projects || []).find(p => p.work_root === workRoot)
    if (project) {
      const sessions = await props.requestRpc('project.sessions.list', { project_id: project.id }) as { sessions?: Array<{ id: string; title: string }> }
      availableSessions.value = sessions.sessions || []
    } else {
      availableSessions.value = []
    }
  } catch (e) { console.error('loadSessions:', e) }
  finally { loadingSessions.value = false }
}

// 项目切换是用户动作：换项目就放弃已选的固定会话并重拉会话列表。
// 编辑回填不走这里，避免把已恢复的固定会话清掉。
function onProjectChange(value: string) {
  formWorkRoot.value = value
  formSessionKey.value = ''
  loadSessions(value)
}

/* ---- 列表数据 ---- */
const byRecency = (a: CoreArrangeJob, b: CoreArrangeJob) => Date.parse(b.updated_at) - Date.parse(a.updated_at)
const filteredJobs = computed(() => {
  if (filter.value === 'active') return jobs.value.filter(j => ACTIVE_STATUSES.has(j.status)).sort(byRecency)
  if (filter.value === 'completed') return jobs.value.filter(j => j.status === 'completed').sort(byRecency)
  if (filter.value === 'failed') return jobs.value.filter(j => j.status === 'failed').sort(byRecency)
  // 全部：未完成的排前面，再按最近更新排序。
  return [...jobs.value].sort((a, b) => (terminal.has(a.status) ? 1 : 0) - (terminal.has(b.status) ? 1 : 0) || byRecency(a, b))
})

async function loadJobs() {
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('arrange.list', props.workRoot ? { work_root: props.workRoot } : {}) as {
      jobs?: CoreArrangeJob[]
      scheduler_notice?: string
    }
    jobs.value = result.jobs ?? []
    schedulerNotice.value = result.scheduler_notice || ''
  }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '读取定时任务失败' }
  finally { loading.value = false }
}

/* ---- 子页切换 ---- */
function openCreateForm(prefill?: { title: string; instruction: string; time: string }) {
  editingJob.value = null
  formTab.value = 'settings'
  formTitle.value = prefill?.title || ''
  formInstruction.value = prefill?.instruction || ''
  formSessionKey.value = ''
  formModelId.value = defaultModelId.value
  formScheduleType.value = prefill ? 'daily' : 'once'
  hasSchedule.value = Boolean(prefill)
  formTimezone.value = 'Asia/Shanghai'
  formDate.value = ''
  formTime.value = prefill?.time || '09:00'
  formDay.value = 1
  formEverySeconds.value = 3600
  formEventType.value = ''
  formMaxRuns.value = undefined
  formWorkRoot.value = props.workRoot || ''
  error.value = ''
  view.value = 'create'
  loadProjects()
  loadModels()
  loadSessions(formWorkRoot.value)
}

function applyTemplate(template: ArrangeTemplate) {
  openCreateForm(template.apply)
}

function parseTriggerIntoForm(job: CoreArrangeJob) {
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
}

function openEditForm(job: CoreArrangeJob) {
  editingJob.value = job
  formTab.value = 'settings'
  formTitle.value = job.title || ''
  formInstruction.value = instruction(job)
  formSessionKey.value = job.session_strategy === 'fixed' ? (job.thread_id || '') : ''
  // 旧任务可能没绑模型：编辑时带出当前默认模型，保存即写回明确模型。
  formModelId.value = job.model_id || defaultModelId.value
  parseTriggerIntoForm(job)
  hasSchedule.value = true
  formWorkRoot.value = (job.work_root || props.workRoot || '')
  error.value = ''
  view.value = 'edit'
  loadProjects()
  loadModels()
  loadSessions(formWorkRoot.value)
}

function goList() {
  view.value = 'list'
  editingJob.value = null
  formTab.value = 'settings'
  loadJobs()
}

/** 返回上一层：子页回列表并消费这次返回；列表页交给外壳关闭整版视图。 */
function handleBack(): boolean {
  if (view.value === 'list') return false
  goList()
  return true
}
function onBackClick() {
  if (!handleBack()) emit('back')
}
defineExpose({ handleBack })

/* ---- 提交 ---- */
function addSchedule() {
  hasSchedule.value = true
}

const scheduleReady = computed(() => {
  if (!hasSchedule.value) return false
  if (formScheduleType.value === 'once') return Boolean(formDate.value)
  if (formScheduleType.value === 'event') return Boolean(formEventType.value.trim())
  return true
})

function buildTrigger(): Record<string, unknown> {
  switch (formScheduleType.value) {
    case 'once':
      // 后端（runtime/arrange.py）从 date/time/timezone 解析单次触发；
      // 只传 local_at 会落进空日期分支而失败。
      return {
        type: 'once',
        date: formDate.value,
        time: formTime.value ? `${formTime.value}:00` : '',
        timezone: formTimezone.value,
      }
    case 'daily':
      return { type: 'calendar', frequency: 'daily', time: formTime.value, timezone: formTimezone.value }
    case 'monthly':
      return { type: 'calendar', frequency: 'monthly', day: formDay.value, time: formTime.value, timezone: formTimezone.value }
    case 'interval':
      return { type: 'interval', every_seconds: formEverySeconds.value }
    case 'event':
      return { type: 'event', event_type: formEventType.value.trim() }
    default:
      return { type: 'once' }
  }
}

async function submitForm() {
  if (!formInstruction.value.trim() || !scheduleReady.value) return
  formSubmitting.value = true
  error.value = ''
  try {
    if (view.value === 'create') {
      await durable.createArrangeJob({
        thread_id: formSessionKey.value,
        work_root: formWorkRoot.value.trim(),
        kind: 'routine',
        operation: 'turn.start',
        payload: { message: formInstruction.value.trim() },
        trigger: buildTrigger(),
        title: formTitle.value.trim() || undefined,
        session_strategy: formSessionKey.value ? 'fixed' : 'new',
        model_id: formModelId.value || undefined,
        max_runs: formMaxRuns.value,
      })
      filter.value = 'all'
      goList()
    } else if (editingJob.value) {
      let updated = await durable.editArrangeJob(editingJob.value.id, {
        instruction: formInstruction.value.trim(),
        trigger: buildTrigger(),
        session_strategy: formSessionKey.value ? 'fixed' : 'new',
        model_id: formModelId.value || undefined,
      })
      const title = formTitle.value.trim()
      if (title && title !== (editingJob.value.title || '')) {
        updated = await durable.renameArrangeJob(editingJob.value.id, title)
      }
      editingJob.value = updated
      jobs.value = jobs.value.map(item => item.id === updated.id ? updated : item)
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '操作失败'
  } finally {
    formSubmitting.value = false
  }
}

async function changeStatus(job: CoreArrangeJob, action: 'pause' | 'resume' | 'cancel') {
  busyIds.value = new Set([...busyIds.value, job.id])
  error.value = ''
  try {
    const updated = await durable.updateArrangeJob(job.id, action)
    jobs.value = jobs.value.map(item => item.id === updated.id ? updated : item)
    if (editingJob.value?.id === updated.id) editingJob.value = updated
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '更新定时任务失败'
  } finally {
    const next = new Set(busyIds.value)
    next.delete(job.id)
    busyIds.value = next
  }
}

/* ---- 运行记录（历史页签，按需加载） ---- */
async function openHistoryTab() {
  formTab.value = 'history'
  if (view.value === 'edit' && editingJob.value) {
    historyLoading.value = true
    try {
      const items = await durable.listArrangeOccurrences(editingJob.value.id)
      occurrences.value = { ...occurrences.value, [editingJob.value.id]: items }
    } catch { /* 记录加载失败不阻塞页面 */ }
    finally { historyLoading.value = false }
  }
}

const currentOccurrences = computed(() => {
  if (view.value !== 'edit' || !editingJob.value) return null
  return occurrences.value[editingJob.value.id] ?? null
})

/* ---- 展示辅助 ---- */
function instruction(job: CoreArrangeJob) { return String(job.payload.message || '未命名定时任务') }
function displayTitle(job: CoreArrangeJob) { return job.title || instruction(job) }
function truncateTitle(text: string) {
  return text.length > 28 ? `${text.slice(0, 28)}…` : text
}
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
function statusColor(status: CoreArrangeJob['status']) {
  const t = 'var(--theme-main-text, #fff)'
  if (status === 'failed') return `color-mix(in srgb, ${t} 30%, var(--red) 70%)`
  if (status === 'paused' || status === 'waiting') return `color-mix(in srgb, ${t} 30%, var(--orange) 70%)`
  return t
}

/* ---- 顶部条标题随子页变化 ---- */
const heading = computed(() => {
  if (view.value === 'create') return { title: '定时任务 › 新建任务', subtitle: '' }
  if (view.value === 'edit' && editingJob.value) {
    return { title: `定时任务 › ${truncateTitle(displayTitle(editingJob.value))}`, subtitle: '' }
  }
  return { title: '定时任务', subtitle: '按计划运行任务，或在需要时随时执行。' }
})
watch(heading, (value) => emit('heading', { ...value }), { immediate: true })

onMounted(loadJobs)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') onBackClick()
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="arrange-view" :aria-busy="loading && view === 'list'">
    <main class="arrange-page full-area-column">
      <FullAreaActions :to-band="bandActions">
        <template v-if="view === 'list'">
          <button class="icon-button" type="button" :disabled="loading" aria-label="刷新" title="刷新" @click="loadJobs">
            <RotateCw :size="14" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <button class="primary-button" type="button" @click="openCreateForm()">创建定时任务</button>
        </template>
        <button
          v-else-if="view === 'create'"
          class="primary-button"
          type="button"
          :disabled="formSubmitting || !formInstruction.trim() || !scheduleReady || !formModelId"
          @click="submitForm"
        >{{ formSubmitting ? '创建中…' : '创建定时任务' }}</button>
        <template v-else-if="editingJob">
          <button
            class="primary-button"
            type="button"
            :disabled="formSubmitting || !formInstruction.trim() || !scheduleReady || !formModelId"
            @click="submitForm"
          >{{ formSubmitting ? '保存中…' : '保存' }}</button>
          <button
            v-if="['scheduled', 'waiting', 'running'].includes(editingJob.status)"
            class="quiet-button"
            type="button"
            :disabled="busyIds.has(editingJob.id)"
            @click="changeStatus(editingJob, 'pause')"
          >暂停</button>
          <button
            v-else-if="editingJob.status === 'paused'"
            class="quiet-button"
            type="button"
            :disabled="busyIds.has(editingJob.id)"
            @click="changeStatus(editingJob, 'resume')"
          >恢复</button>
          <button
            v-if="!terminal.has(editingJob.status)"
            class="quiet-button danger"
            type="button"
            :disabled="busyIds.has(editingJob.id)"
            @click="changeStatus(editingJob, 'cancel')"
          >取消任务</button>
        </template>
      </FullAreaActions>

      <div class="arrange-mobile-head">
        <button class="arrange-back" type="button" aria-label="返回" title="返回" @click="onBackClick">
          <ArrowLeft :size="16" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <div v-if="view === 'list'" class="arrange-head-copy">
          <h1 class="arrange-title">定时任务</h1>
          <p class="arrange-subtitle">按计划运行任务，或在需要时随时执行。</p>
        </div>
        <p v-else-if="view === 'create'" class="arrange-crumb">定时任务 <span class="crumb-sep" aria-hidden="true">›</span> 新建任务</p>
        <p v-else class="arrange-crumb">定时任务 <span class="crumb-sep" aria-hidden="true">›</span> {{ editingJob ? truncateTitle(displayTitle(editingJob)) : '' }}</p>
      </div>

      <!-- 列表 -->
      <template v-if="view === 'list'">
        <p v-if="schedulerNotice" class="arrange-notice" role="status">
          <CircleAlert :size="14" :stroke-width="1.8" aria-hidden="true" />
          <span>{{ schedulerNotice }}</span>
        </p>

        <p v-if="loading" class="arrange-loading" role="status">正在读取定时任务…</p>

        <div v-else-if="error" class="arrange-error" role="alert">
          <span>{{ error }}</span>
          <button type="button" @click="loadJobs">重试</button>
        </div>

        <template v-else>
          <div class="filter-tabs" role="group" aria-label="按状态筛选">
            <button
              v-for="f in filterDefs"
              :key="f.id"
              type="button"
              :class="{ active: filter === f.id }"
              :aria-pressed="filter === f.id"
              @click="filter = f.id"
            >{{ f.label }}</button>
          </div>

          <section class="arrange-section">
            <h3 class="section-label">已创建任务</h3>
            <div v-if="jobs.length === 0" class="full-area-empty" data-arrange-empty>
              <span class="full-area-empty-icon" aria-hidden="true"><CalendarClock :size="18" :stroke-width="1.8" /></span>
              <h2 class="full-area-empty-title">还没有定时任务</h2>
              <p class="full-area-empty-hint">
                定时任务是一句交给 Agent 的长期指令：到点它会自己开工，跑完把结果留在会话里。
                点右上角「创建定时任务」，或直接在聊天里说「每天九点把 XX 做一遍」。
              </p>
            </div>
            <p v-else-if="filteredJobs.length === 0" class="tab-empty">这个状态下暂无任务。</p>
            <div v-else class="card-list" role="list">
              <article
                v-for="job in filteredJobs"
                :key="job.id"
                class="arrange-card"
                role="listitem"
                tabindex="0"
                :aria-label="`打开 ${displayTitle(job)}`"
                @click="openEditForm(job)"
                @keydown.enter.prevent="openEditForm(job)"
              >
                <h4 class="card-title">{{ displayTitle(job) }}</h4>
                <p class="card-desc">{{ instruction(job) }}</p>
                <footer class="card-foot">
                  <span class="status-chip" :style="{ color: statusColor(job.status) }">
                    <span class="status-dot" :style="{ background: statusColor(job.status) }" aria-hidden="true" />
                    {{ statusLabel(job.status) }}
                  </span>
                  <span class="schedule-chip">
                    <Clock3 :size="12" :stroke-width="1.8" aria-hidden="true" />
                    {{ schedule(job) }}
                  </span>
                  <span class="run-count">已运行 {{ job.run_count }} 次</span>
                </footer>
              </article>
            </div>
          </section>

          <section class="arrange-section">
            <h3 class="section-label">定时任务模板</h3>
            <div class="template-grid">
              <button v-for="t in templates" :key="t.id" type="button" class="template-card" @click="applyTemplate(t)">
                <span class="template-head">
                  <component :is="t.icon" :size="15" :stroke-width="1.8" aria-hidden="true" />
                  <strong>{{ t.name }}</strong>
                </span>
                <span class="template-desc">{{ t.description }}</span>
                <span class="template-schedule">{{ t.scheduleLabel }}</span>
              </button>
            </div>
          </section>
        </template>
      </template>

      <!-- 新建 / 编辑 -->
      <div v-else class="form-shell">
        <header class="form-heading">
          <h2>{{ view === 'create' ? '新建定时任务' : '编辑定时任务' }}</h2>
          <p>{{ view === 'create' ? '配置任务的执行时间、指令和运行方式。' : '调整此任务的执行时间、指令和运行方式。' }}</p>
        </header>

        <div class="form-tabs" role="tablist" aria-label="任务页签">
          <button type="button" role="tab" :aria-selected="formTab === 'settings'" :class="{ active: formTab === 'settings' }" @click="formTab = 'settings'">设置</button>
          <button type="button" role="tab" :aria-selected="formTab === 'history'" :class="{ active: formTab === 'history' }" @click="openHistoryTab">历史</button>
        </div>

        <div v-if="formTab === 'settings'" class="form-body">
          <div v-if="view === 'edit' && editingJob" class="form-field">
            <span class="field-label">状态</span>
            <span class="status-chip" :style="{ color: statusColor(editingJob.status) }">
              <span class="status-dot" :style="{ background: statusColor(editingJob.status) }" aria-hidden="true" />
              {{ statusLabel(editingJob.status) }}
            </span>
            <p v-if="editingJob.last_error" class="form-error">{{ editingJob.last_error }}</p>
          </div>

          <label class="form-field">
            <span class="field-label">任务标题</span>
            <input v-model="formTitle" placeholder="未命名定时任务" />
          </label>

          <div class="form-field">
            <span class="field-label">调度</span>
            <button v-if="!hasSchedule" type="button" class="schedule-add" @click="addSchedule">
              <Plus :size="14" :stroke-width="1.8" aria-hidden="true" />
              添加计划
            </button>
            <div v-else class="schedule-row">
              <UiSelect
                class="schedule-select"
                :model-value="formScheduleType"
                :options="scheduleTypeOptions"
                aria-label="调度方式"
                @update:model-value="formScheduleType = $event as 'once' | 'daily' | 'monthly' | 'interval' | 'event'"
              />
              <template v-if="formScheduleType === 'once'">
                <input v-model="formDate" type="date" aria-label="日期" />
                <input v-model="formTime" type="time" aria-label="时间" />
              </template>
              <template v-else-if="formScheduleType === 'daily'">
                <span class="schedule-join">于</span>
                <input v-model="formTime" type="time" aria-label="时间" />
              </template>
              <template v-else-if="formScheduleType === 'monthly'">
                <span class="schedule-join">每月</span>
                <input v-model.number="formDay" type="number" min="1" max="31" aria-label="几号" />
                <span class="schedule-join">日</span>
                <input v-model="formTime" type="time" aria-label="时间" />
              </template>
              <template v-else-if="formScheduleType === 'interval'">
                <span class="schedule-join">每</span>
                <input v-model.number="formEverySeconds" type="number" min="1" aria-label="间隔秒数" />
                <span class="schedule-join">秒</span>
              </template>
              <input v-else v-model="formEventType" placeholder="事件类型，如 artifact.changed" aria-label="事件类型" />
              <input
                v-if="formScheduleType === 'once' || formScheduleType === 'daily' || formScheduleType === 'monthly'"
                v-model="formTimezone"
                class="schedule-timezone"
                placeholder="Asia/Shanghai"
                aria-label="时区"
              />
              <button
                v-if="view === 'create'"
                type="button"
                class="schedule-remove"
                aria-label="移除计划"
                title="移除计划"
                @click="hasSchedule = false"
              >
                <Trash2 :size="14" :stroke-width="1.8" aria-hidden="true" />
              </button>
            </div>
            <label v-if="view === 'create'" class="max-runs">
              最多运行次数
              <input v-model.number="formMaxRuns" type="number" min="1" placeholder="留空不限" />
            </label>
          </div>

          <div class="form-field">
            <span class="field-label">指令</span>
            <div class="instruction-shell">
              <textarea
                v-model="formInstruction"
                rows="7"
                placeholder="例如：Review 最近 24 小时的提交，总结可能引入的 bug 和修复建议"
              />
              <div class="instruction-meta">
                <div class="instruction-meta-left">
                  <UiSelect
                    v-if="projectOptions.length"
                    class="meta-select"
                    :model-value="formWorkRoot"
                    :options="projectOptions"
                    direction="up"
                    aria-label="项目"
                    @update:model-value="onProjectChange"
                  />
                  <input v-else v-model="formWorkRoot" class="meta-input" placeholder="项目目录" aria-label="项目目录" />
                  <UiSelect
                    class="meta-select"
                    :model-value="formSessionKey"
                    :options="threadOptions"
                    direction="up"
                    aria-label="会话"
                    :disabled="loadingSessions"
                    @update:model-value="formSessionKey = $event"
                  />
                </div>
                <UiSelect
                  class="meta-select meta-select--model"
                  :model-value="formModelId"
                  :options="modelOptions"
                  direction="up"
                  menu-align="right"
                  placeholder="选择模型"
                  aria-label="模型"
                  @update:model-value="formModelId = $event"
                />
              </div>
            </div>
          </div>

          <div v-if="error" class="form-error" role="alert">{{ error }}</div>
        </div>

        <div v-else class="history-panel">
          <p v-if="view === 'create'" class="tab-empty">任务创建后，这里会显示每次运行的时间与结果。</p>
          <p v-else-if="historyLoading" class="tab-empty" role="status">读取运行记录…</p>
          <p v-else-if="!currentOccurrences || currentOccurrences.length === 0" class="tab-empty">还没有运行记录。</p>
          <template v-else>
            <div v-for="occ in currentOccurrences" :key="occ.id" class="history-item">
              <span class="history-time">{{ formatTime(occ.scheduled_at) }}</span>
              <span class="history-status" :class="occ.status">{{ occ.status === 'completed' ? '完成' : occ.status === 'failed' ? '失败' : occ.status }}</span>
              <span v-if="occ.attempt_count > 1" class="history-attempts">×{{ occ.attempt_count }}</span>
              <span v-if="occ.last_error" class="history-error">{{ occ.last_error }}</span>
            </div>
          </template>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
/* ── 整版界面：内容落在与会话同一条轴线上（full-area-column） ── */
.arrange-view {
  --text: var(--theme-main-text);
}

.arrange-page {
  padding: var(--space-4) 0 var(--space-5);
}

/* 手机没有顶部条，标题与返回键留在版面里；桌面由顶部条承担。 */
.arrange-mobile-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.arrange-head-copy { min-width: 0; }

.arrange-back {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  margin-top: 2px;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 68%, transparent);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}

.arrange-back:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

h1 { margin: 0 0 2px; font-size: 17px; font-weight: 700; letter-spacing: 0; }
.arrange-title { font-size: 17px; }
.arrange-subtitle { margin: 0; font-size: 12px; color: color-mix(in srgb, var(--text) 62%, transparent); }
.arrange-crumb { margin: 4px 0 0; font-size: 13px; color: color-mix(in srgb, var(--text) 62%, transparent); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.crumb-sep { margin: 0 2px; color: color-mix(in srgb, var(--text) 40%, transparent); }
p { margin: 0; }
button { font: inherit; }

/* 按钮：与资料库同一套（一种配方，两种语气）。 */
.quiet-button, .primary-button, .icon-button {
  min-height: 28px;
  padding: 5px var(--space-3);
  border-radius: var(--radius-sm);
  font-size: 12.5px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), filter var(--dur-fast) var(--ease-out);
}

.quiet-button, .icon-button {
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  background: transparent;
  color: color-mix(in srgb, var(--text) 78%, transparent);
}

.quiet-button:hover:not(:disabled), .icon-button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  padding: 0;
}

.quiet-button.danger { color: var(--red); border-color: color-mix(in srgb, var(--red) 35%, transparent); }
.quiet-button.danger:hover:not(:disabled) { background: color-mix(in srgb, var(--red) 10%, transparent); color: var(--red); }

.primary-button {
  border: 1px solid transparent;
  background: var(--theme-control-background);
  color: var(--theme-control-text);
  font-weight: 600;
}

.primary-button:hover:not(:disabled) { filter: brightness(0.94); }

.primary-button:disabled, .quiet-button:disabled, .icon-button:disabled { opacity: .45; cursor: default; }

.arrange-loading { padding: var(--space-4) 0; font-size: 13px; color: color-mix(in srgb, var(--text) 62%, transparent); }
.arrange-error { display: flex; align-items: center; justify-content: space-between; gap: var(--space-4); padding: var(--space-4) 0; color: var(--red); font-size: 13px; }
.arrange-error button { flex: none; min-height: 28px; padding: 5px var(--space-3); border: 1px solid currentColor; border-radius: var(--radius-sm); background: transparent; color: inherit; cursor: pointer; font: inherit; font-size: 12.5px; }

/* 调度器提示条 */
.arrange-notice {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) 4%, transparent);
  color: color-mix(in srgb, var(--text) 72%, transparent);
  font-size: 12.5px;
}
.arrange-notice svg { flex: 0 0 auto; color: color-mix(in srgb, var(--text) 55%, transparent); }

/* 状态筛选 */
.filter-tabs { display: flex; align-items: center; gap: var(--space-1); margin-bottom: var(--space-4); }
.filter-tabs button {
  padding: 4px var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12.5px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.filter-tabs button:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.filter-tabs button.active { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); color: var(--text); font-weight: 600; }

/* 分区 */
.arrange-section { display: grid; gap: var(--space-2); }
.arrange-section + .arrange-section { margin-top: var(--space-5); }
.section-label { margin: 0 0 var(--space-1); font-size: 13px; font-weight: 650; color: color-mix(in srgb, var(--text) 85%, transparent); }
.tab-empty { margin: 0; padding: var(--space-3) 0; font-size: 13px; color: color-mix(in srgb, var(--text) 62%, transparent); }

/* 任务卡片 */
.card-list { display: grid; gap: var(--space-2); }

.arrange-card {
  display: grid;
  gap: 6px;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--theme-main-border, color-mix(in srgb, var(--text) 10%, transparent));
  border-radius: var(--radius);
  background: var(--theme-main-soft-background, color-mix(in srgb, var(--text) 4%, transparent));
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}
.arrange-card:hover { background: color-mix(in srgb, var(--text) 7%, transparent); }
.arrange-card:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

.card-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 650;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-desc {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}

.card-foot { display: flex; align-items: center; gap: var(--space-3); margin-top: 2px; min-width: 0; }
.status-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; flex: 0 0 auto; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.schedule-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--green) 12%, transparent);
  color: color-mix(in srgb, var(--green) 78%, var(--text) 22%);
  font-size: 12px;
  white-space: nowrap;
}
.run-count { margin-left: auto; font-size: 12px; color: color-mix(in srgb, var(--text) 55%, transparent); flex: 0 0 auto; }

/* 模板卡片 */
.template-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--space-2); }
.template-card {
  display: grid;
  gap: 6px;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--theme-main-border, color-mix(in srgb, var(--text) 10%, transparent));
  border-radius: var(--radius);
  background: var(--theme-main-soft-background, color-mix(in srgb, var(--text) 4%, transparent));
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}
.template-card:hover { background: color-mix(in srgb, var(--text) 7%, transparent); }
.template-card:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.template-head { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text); }
.template-head svg { color: color-mix(in srgb, var(--text) 65%, transparent); }
.template-desc {
  font-size: 12.5px;
  line-height: 1.6;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.template-schedule { font-size: 12px; color: color-mix(in srgb, var(--text) 55%, transparent); }

/* ---- 新建 / 编辑 ---- */
.form-shell { display: grid; gap: var(--space-4); }
.form-heading h2 { margin: 0 0 2px; font-size: 17px; font-weight: 700; }
.form-heading p { margin: 0; font-size: 12.5px; color: color-mix(in srgb, var(--text) 62%, transparent); }

.form-tabs {
  display: inline-flex;
  gap: 2px;
  justify-self: start;
  padding: 2px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) 6%, transparent);
}
.form-tabs button {
  padding: 4px var(--space-3);
  border: 0;
  border-radius: calc(var(--radius-sm) - 2px);
  background: transparent;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12.5px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.form-tabs button:hover { color: var(--text); }
.form-tabs button.active { background: var(--theme-main-background, var(--bg)); color: var(--text); font-weight: 600; }

.form-body { display: flex; flex-direction: column; gap: var(--space-4); }
.form-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.field-label { font-size: 13px; font-weight: 600; color: color-mix(in srgb, var(--text) 85%, transparent); }
.form-field em { font-style: normal; color: var(--orange); }
.form-error { margin: 0; color: var(--red); font-size: 12.5px; white-space: pre-wrap; word-break: break-word; }

.form-field input, .schedule-row input, .meta-input {
  box-sizing: border-box;
  padding: 7px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  font: inherit;
  font-size: 13.5px;
}
.form-field input:focus, .schedule-row input:focus, .meta-input:focus { outline: 0; }

/* 调度行 */
.schedule-add {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--space-1);
  padding: 10px var(--space-3);
  border: 1px dashed color-mix(in srgb, var(--text) 18%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 13px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}
.schedule-add:hover { border-color: color-mix(in srgb, var(--text) 30%, transparent); background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }

.schedule-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding: 6px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
}
.schedule-row input[type='date'], .schedule-row input[type='time'], .schedule-row input[type='number'] { width: 120px; padding: 5px var(--space-2); font-size: 12.5px; }
.schedule-row input[type='text'], .schedule-row input:not([type]) { flex: 1 1 140px; padding: 5px var(--space-2); font-size: 12.5px; }
.schedule-join { font-size: 12.5px; color: color-mix(in srgb, var(--theme-composer-text) 55%, transparent); flex: 0 0 auto; }
.schedule-select { flex: 0 0 auto; }
.schedule-row input.schedule-timezone { flex: 0 0 auto; width: 120px; }
.schedule-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-left: auto;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-composer-text) 55%, transparent);
  cursor: pointer;
  flex: 0 0 auto;
}
.schedule-remove:hover { background: color-mix(in srgb, var(--red) 12%, transparent); color: var(--red); }

.max-runs { display: flex; align-items: center; gap: var(--space-2); font-size: 12.5px; color: color-mix(in srgb, var(--text) 62%, transparent); }
.max-runs input { width: 120px; padding: 5px var(--space-2); font-size: 12.5px; }

/* 指令：正文 + 底部元信息条一体 */
.instruction-shell {
  display: flex;
  flex-direction: column;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
}
.instruction-shell textarea {
  box-sizing: border-box;
  width: 100%;
  min-height: 150px;
  padding: var(--space-3);
  border: 0;
  background: transparent;
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  font: inherit;
  font-size: 13.5px;
  line-height: 1.65;
  resize: vertical;
}
.instruction-shell textarea:focus { outline: 0; }
.instruction-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: 4px var(--space-2);
  border-top: 1px solid color-mix(in srgb, var(--theme-composer-text) 10%, transparent);
}
.instruction-meta-left { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.meta-select { flex: 0 1 auto; min-width: 0; }
.meta-select :deep(.ui-select-trigger) {
  min-height: 28px;
  border: 0;
  background: transparent;
  font-size: 12.5px;
}
.meta-input { flex: 1 1 120px; border: 0; background: transparent; font-size: 12.5px; }

/* 历史 */
.history-panel { display: grid; }
.history-item {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  font-size: 12.5px;
}
.history-item + .history-item { border-top: 1px solid color-mix(in srgb, var(--text) 6%, transparent); }
.history-time { color: color-mix(in srgb, var(--text) 65%, transparent); min-width: 150px; flex: 0 0 auto; }
.history-status { flex: 0 0 auto; color: color-mix(in srgb, var(--text) 65%, transparent); }
.history-status.failed { color: var(--red); }
.history-status.completed { color: color-mix(in srgb, var(--text) 85%, transparent); }
.history-attempts { color: color-mix(in srgb, var(--text) 55%, transparent); font-size: 11.5px; }
.history-error { color: color-mix(in srgb, var(--red) 80%, transparent); font-size: 12px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

button:disabled { cursor: default; opacity: .5; }

/* 桌面：标题与返回键由顶部条承担，手机头整块收起。 */
@media (min-width: 641px) {
  .arrange-mobile-head {
    display: none;
  }
}

@media (max-width: 700px) {
  .arrange-page { padding: 24px 18px; }
  .arrange-card, .template-card { padding: 14px 16px; }
  .template-grid { grid-template-columns: 1fr; }
  .card-foot { flex-wrap: wrap; row-gap: 4px; }
  .run-count { flex-basis: 100%; margin-left: 0; }
  .quiet-button, .primary-button { min-height: 36px; }
  .instruction-meta { flex-wrap: wrap; }
}
</style>
