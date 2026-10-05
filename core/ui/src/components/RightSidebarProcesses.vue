<template>
  <section class="runtime-widget core-process-panel" :aria-labelledby="titleId">
    <div class="runtime-widget-head core-process-panel__head">
      <div>
        <h3 :id="titleId">{{ title }}</h3>
        <p>{{ summaryText }}</p>
      </div>
      <button
        type="button"
        class="core-process-panel__refresh"
        :aria-label="loading ? '正在刷新进程列表' : '刷新进程列表'"
        :title="loading ? '刷新中…' : '刷新'"
        @click="fetchProcesses()"
      >
        <RotateCw :size="13" :stroke-width="1.8" :class="{ 'is-spinning': loading }" aria-hidden="true" />
      </button>
    </div>

    <div class="core-process-panel__list">
      <p v-if="errorText" class="core-process-panel__notice is-error" role="alert">{{ errorText }}</p>
      <p v-else-if="actionError" class="core-process-panel__notice is-error" role="alert">{{ actionError }}</p>
      <p v-else-if="loading && processes.length === 0" class="core-process-panel__notice" role="status">
        正在读取后台进程…
      </p>

      <div v-for="process in processes" :key="process.pid" class="core-process-panel__item" :data-process-pid="process.pid">
        <div class="core-process-panel__row">
          <button
            type="button"
            class="core-process-panel__main"
            :aria-expanded="expandedPid === process.pid"
            @click="toggleExpanded(process)"
          >
            <span class="core-process-panel__dot" :class="'is-' + stateOf(process)" aria-hidden="true" />
            <span class="core-process-panel__pid">#{{ process.pid }}</span>
            <span class="core-process-panel__command" :title="process.command || ''">{{ process.command || '未知命令' }}</span>
            <span class="core-process-panel__elapsed">{{ elapsedLabel(process) }}</span>
            <span class="core-process-panel__state" :data-state="stateOf(process)">{{ stateText(process) }}</span>
          </button>
          <button
            v-if="process.can_terminate"
            type="button"
            class="core-process-panel__action is-danger"
            :disabled="pendingPid === process.pid"
            :aria-label="'终止进程 ' + process.pid"
            title="终止进程"
            @click="killProcess(process)"
          >
            <Square :size="12" :stroke-width="2" aria-hidden="true" />
          </button>
          <button
            v-else-if="!process.alive"
            type="button"
            class="core-process-panel__action"
            :disabled="pendingPid === process.pid"
            :aria-label="'移除进程 ' + process.pid + ' 的记录'"
            title="移除记录"
            @click="forgetProcess(process)"
          >
            <X :size="13" :stroke-width="1.8" aria-hidden="true" />
          </button>
        </div>

        <Transition name="core-process-detail">
          <div v-if="expandedPid === process.pid" class="core-process-panel__detail">
            <p class="core-process-panel__meta">
              <span>PID {{ process.pid }}</span>
              <span v-if="process.persistent">长期驻留（轮次结束后继续运行）</span>
              <span v-else>随轮次结束清理</span>
            </p>
            <div class="core-process-panel__log-tabs" role="tablist" aria-label="进程日志">
              <button
                type="button"
                role="tab"
                :aria-selected="logStream === 'stdout'"
                :class="{ active: logStream === 'stdout' }"
                @click="selectLogStream('stdout')"
              >标准输出</button>
              <button
                type="button"
                role="tab"
                :aria-selected="logStream === 'stderr'"
                :class="{ active: logStream === 'stderr' }"
                @click="selectLogStream('stderr')"
              >错误输出</button>
            </div>
            <pre class="core-process-panel__log" role="status">{{ logText }}</pre>
          </div>
        </Transition>
      </div>

      <p v-if="processes.length === 0 && !loading && !errorText" class="core-process-panel__empty">
        没有正在登记的后台进程
      </p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { RotateCw, Square, X } from 'lucide-vue-next'
import type { RightSidebarRpc } from '../right-sidebar/types'

interface BackgroundProcessItem {
  pid: number
  session_id?: string
  command?: string
  started_at?: number
  persistent?: boolean
  stdout_log?: string
  stderr_log?: string
  alive?: boolean
  owned?: boolean
  can_terminate?: boolean
}

const props = withDefaults(defineProps<{
  title?: string
  requestRpc?: RightSidebarRpc
  sessionId?: string | null
  /** Live backend events; process/changed and command tool activity trigger a refresh. */
  processSignal?: unknown
}>(), {
  title: 'Background Processes',
  requestRpc: undefined,
  sessionId: null,
  processSignal: undefined,
})

const instanceId = useId().replace(/[^a-zA-Z0-9_-]/g, '')
const titleId = 'core-process-title-' + instanceId

const processes = ref<BackgroundProcessItem[]>([])
const loading = ref(false)
const errorText = ref('')
const actionError = ref('')
const expandedPid = ref(0)
const logStream = ref<'stdout' | 'stderr'>('stdout')
const logState = ref<{ content: string; truncated: boolean; missing: boolean }>({ content: '', truncated: false, missing: false })
const pendingPid = ref(0)
const nowTick = ref(Date.now())
let loadRevision = 0
let pollTimer: ReturnType<typeof setInterval> | null = null
let tickTimer: ReturnType<typeof setInterval> | null = null
let actionErrorTimer: ReturnType<typeof setTimeout> | null = null
let signalFetchAt = 0

const summaryText = computed(() => {
  if (errorText.value) return '读取失败'
  const running = processes.value.filter((process) => process.alive).length
  if (processes.value.length > 0) return `${processes.value.length} 个进程 · ${running} 个运行中`
  if (loading.value) return '读取中'
  return '没有长期后台进程'
})

const logText = computed(() => {
  if (logState.value.missing) return '（暂无日志输出）'
  let text = logState.value.content
  if (logState.value.truncated) text = '[…截断，仅显示尾部…]\n' + text
  return text || '（日志为空）'
})

async function fetchProcesses(): Promise<void> {
  const requestRpc = props.requestRpc
  const sessionId = props.sessionId
  const revision = ++loadRevision
  if (!requestRpc || !sessionId) {
    processes.value = []
    loading.value = false
    errorText.value = ''
    return
  }
  loading.value = true
  try {
    const response = await requestRpc('process.list', { session_id: sessionId, thread_id: sessionId })
    if (revision !== loadRevision) return
    const list = response && Array.isArray(response.processes) ? response.processes : []
    processes.value = list
      .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
      .map(normalizeProcess)
      .filter((item): item is BackgroundProcessItem => item !== null)
    errorText.value = ''
  } catch (cause) {
    if (revision !== loadRevision) return
    errorText.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    if (revision === loadRevision) loading.value = false
  }
}

function normalizeProcess(value: Record<string, unknown>): BackgroundProcessItem | null {
  const pid = Number(value.pid)
  if (!Number.isFinite(pid) || pid <= 0) return null
  return {
    pid,
    session_id: typeof value.session_id === 'string' ? value.session_id : undefined,
    command: typeof value.command === 'string' ? value.command : undefined,
    started_at: typeof value.started_at === 'number' ? value.started_at : undefined,
    persistent: value.persistent === true,
    stdout_log: typeof value.stdout_log === 'string' ? value.stdout_log : undefined,
    stderr_log: typeof value.stderr_log === 'string' ? value.stderr_log : undefined,
    alive: value.alive === true,
    owned: value.owned === true,
    can_terminate: value.can_terminate === true,
  }
}

function stateOf(process: BackgroundProcessItem): 'running' | 'lost' | 'exited' {
  if (process.alive) return process.owned ? 'running' : 'lost'
  return 'exited'
}

function stateText(process: BackgroundProcessItem): string {
  const state = stateOf(process)
  if (state === 'running') return '运行中'
  if (state === 'lost') return '已失联'
  return '已退出'
}

function elapsedLabel(process: BackgroundProcessItem): string {
  if (!process.alive) return '—'
  if (typeof process.started_at !== 'number' || !Number.isFinite(process.started_at)) return '—'
  const elapsedSeconds = Math.max(0, nowTick.value / 1000 - process.started_at)
  if (elapsedSeconds < 60) return `${Math.floor(elapsedSeconds)}s`
  const minutes = Math.floor(elapsedSeconds / 60)
  if (minutes < 60) return `${minutes}m ${String(Math.floor(elapsedSeconds % 60)).padStart(2, '0')}s`
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`
}

function toggleExpanded(process: BackgroundProcessItem): void {
  if (expandedPid.value === process.pid) {
    expandedPid.value = 0
    return
  }
  expandedPid.value = process.pid
  logStream.value = 'stdout'
  void fetchLog(process, 'stdout')
}

async function selectLogStream(stream: 'stdout' | 'stderr'): Promise<void> {
  logStream.value = stream
  const process = processes.value.find((item) => item.pid === expandedPid.value)
  if (process) await fetchLog(process, stream)
}

async function fetchLog(process: BackgroundProcessItem, stream: 'stdout' | 'stderr'): Promise<void> {
  const requestRpc = props.requestRpc
  if (!requestRpc || !props.sessionId) return
  try {
    const response = await requestRpc('process.log', {
      thread_id: props.sessionId,
      pid: process.pid,
      stream,
      max_bytes: 16384,
    })
    logState.value = {
      content: typeof response?.content === 'string' ? response.content : '',
      truncated: response?.truncated === true,
      missing: response?.missing === true,
    }
  } catch (cause) {
    logState.value = {
      content: cause instanceof Error ? cause.message : String(cause),
      truncated: false,
      missing: true,
    }
  }
}

async function killProcess(process: BackgroundProcessItem): Promise<void> {
  const requestRpc = props.requestRpc
  if (!requestRpc || !props.sessionId) return
  pendingPid.value = process.pid
  try {
    await requestRpc('process.kill', { thread_id: props.sessionId, pid: process.pid })
    clearActionError()
    if (expandedPid.value === process.pid) expandedPid.value = 0
  } catch (cause) {
    showActionError(cause instanceof Error ? cause.message : String(cause))
  } finally {
    pendingPid.value = 0
    void fetchProcesses()
  }
}

async function forgetProcess(process: BackgroundProcessItem): Promise<void> {
  const requestRpc = props.requestRpc
  if (!requestRpc || !props.sessionId) return
  pendingPid.value = process.pid
  try {
    await requestRpc('process.forget', { thread_id: props.sessionId, pid: process.pid })
    clearActionError()
    if (expandedPid.value === process.pid) expandedPid.value = 0
  } catch (cause) {
    showActionError(cause instanceof Error ? cause.message : String(cause))
  } finally {
    pendingPid.value = 0
    void fetchProcesses()
  }
}

function showActionError(message: string): void {
  actionError.value = message
  if (actionErrorTimer) clearTimeout(actionErrorTimer)
  actionErrorTimer = setTimeout(() => { actionError.value = '' }, 5000)
}

function clearActionError(): void {
  actionError.value = ''
  if (actionErrorTimer) clearTimeout(actionErrorTimer)
  actionErrorTimer = null
}

function isProcessSignal(event: unknown): boolean {
  if (!event || typeof event !== 'object') return false
  const record = event as Record<string, unknown>
  const method = String(record.method || '')
  if (method === 'process/changed') return true
  if (method !== 'core/runItem') return false
  const payload = record.payload ?? record.params
  // Command tool activity (start/finish) may add or retire processes; the
  // throttled refresh keeps the panel fresh without stringifying every delta.
  try {
    return JSON.stringify(payload ?? {}).includes('"run_command"')
  } catch {
    return false
  }
}

watch(() => props.sessionId, () => {
  expandedPid.value = 0
  void fetchProcesses()
})
watch(() => props.processSignal, (event) => {
  if (!isProcessSignal(event)) return
  const now = Date.now()
  if (now - signalFetchAt < 1500) return
  signalFetchAt = now
  void fetchProcesses()
})

onMounted(() => {
  void fetchProcesses()
  pollTimer = setInterval(() => { void fetchProcesses() }, 4000)
  tickTimer = setInterval(() => { nowTick.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  loadRevision += 1
  if (pollTimer) clearInterval(pollTimer)
  if (tickTimer) clearInterval(tickTimer)
  if (actionErrorTimer) clearTimeout(actionErrorTimer)
  pollTimer = null
  tickTimer = null
  actionErrorTimer = null
})

defineExpose({ fetchProcesses })
</script>

<style scoped>
.core-process-panel {
  --text: var(--theme-backdrop-text);
  color: var(--text);
}

.core-process-panel__head {
  align-items: center;
}

.core-process-panel__head p {
  font-variant-numeric: tabular-nums;
}

.core-process-panel__refresh {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  min-height: 26px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 58%, transparent);
  cursor: pointer;
}

.core-process-panel__refresh:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.core-process-panel__refresh:focus-visible,
.core-process-panel__main:focus-visible,
.core-process-panel__action:focus-visible,
.core-process-panel__log-tabs button:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent);
  outline-offset: 1px;
}

.core-process-panel__refresh svg.is-spinning {
  animation: core-process-spin 1s linear infinite;
}

@keyframes core-process-spin {
  to { transform: rotate(360deg); }
}

.core-process-panel__list {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.core-process-panel__notice {
  min-height: 2.25rem;
  margin: 0;
  padding: .5rem;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-size: .75rem;
  line-height: 1.45;
}

.core-process-panel__notice.is-error {
  color: color-mix(in srgb, var(--red, #f5555d) 78%, var(--theme-backdrop-text, currentColor));
}

.core-process-panel__item {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.core-process-panel__row {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: .25rem;
}

.core-process-panel__main {
  min-width: 0;
  min-height: 2.25rem;
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: .45rem;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  padding: 0 .5rem;
  text-align: left;
  font: inherit;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

.core-process-panel__main:hover {
  transform: translateX(2px);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.core-process-panel__main:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-process-panel__dot {
  width: .625rem;
  height: .625rem;
  border-radius: 50%;
  background: color-mix(in srgb, var(--text) 24%, transparent);
}

.core-process-panel__dot.is-running {
  background: var(--green, #32d17d);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--green, #32d17d) 22%, transparent);
}

.core-process-panel__dot.is-lost {
  background: color-mix(in srgb, var(--orange, #ff9142) 78%, var(--theme-backdrop-background));
}

.core-process-panel__dot.is-exited {
  background: color-mix(in srgb, var(--text) 28%, transparent);
}

.core-process-panel__pid {
  color: color-mix(in srgb, var(--text) 55%, transparent);
  font-size: .6875rem;
  font-family: var(--font-mono);
  white-space: nowrap;
}

.core-process-panel__command {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: .78125rem;
  font-weight: 600;
  line-height: 1.35;
}

.core-process-panel__elapsed {
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: .625rem;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.core-process-panel__state {
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: .6875rem;
  white-space: nowrap;
}

.core-process-panel__action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  min-height: 26px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 58%, transparent);
  cursor: pointer;
}

.core-process-panel__action:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.core-process-panel__action.is-danger:hover:not(:disabled) {
  background: color-mix(in srgb, var(--red, #f5555d) 18%, transparent);
  color: color-mix(in srgb, var(--red, #f5555d) 85%, var(--text));
}

.core-process-panel__action:disabled {
  opacity: .45;
  cursor: default;
}

.core-process-panel__detail {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
  margin: 0 0 .25rem .5rem;
  padding: var(--space-2);
  border-left: 1px solid color-mix(in srgb, var(--text) 16%, transparent);
}

.core-process-panel__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 0;
  color: color-mix(in srgb, var(--text) 52%, transparent);
  font-size: .6875rem;
  line-height: 1.4;
}

.core-process-panel__log-tabs {
  display: inline-flex;
  gap: 2px;
}

.core-process-panel__log-tabs button {
  min-height: 22px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 55%, transparent);
  padding: 0 var(--space-2);
  font: inherit;
  font-size: .6875rem;
  cursor: pointer;
}

.core-process-panel__log-tabs button:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.core-process-panel__log-tabs button.active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  color: var(--text);
}

.core-process-panel__log {
  max-height: 11rem;
  overflow: auto;
  margin: 0;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-sunken-background, transparent) 88%, transparent);
  color: color-mix(in srgb, var(--text) 82%, transparent);
  font-family: var(--font-mono);
  font-size: .6875rem;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.core-process-panel__empty {
  margin: 0;
  padding: .5rem;
  color: color-mix(in srgb, var(--text) 56%, transparent);
  font-size: .75rem;
  line-height: 1.5;
}

.core-process-detail-enter-active,
.core-process-detail-leave-active {
  transition:
    grid-template-rows var(--dur-slow) var(--ease-out),
    opacity var(--dur-base) var(--ease-out);
}

.core-process-detail-enter-from,
.core-process-detail-leave-to {
  opacity: 0;
}

@media (pointer: coarse) {
  .core-process-panel__main,
  .core-process-panel__action {
    min-height: 2.75rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .core-process-panel__refresh svg.is-spinning { animation: none; }
  .core-process-panel__main,
  .core-process-detail-enter-active,
  .core-process-detail-leave-active {
    transition: none;
  }
  .core-process-panel__main:hover {
    transform: none;
  }
}
</style>
