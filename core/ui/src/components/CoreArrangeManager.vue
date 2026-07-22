<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { CoreArrangeJob } from '../durable/types'
import { listArrangeJobs, updateArrangeJob, renameArrangeJob, editArrangeJob as editArrangeJobApi, listArrangeOccurrences } from '../durable/api'

defineEmits<{ back: [] }>()

const jobs = ref<CoreArrangeJob[]>([])
const loading = ref(false)
const error = ref('')
const busyIds = ref(new Set<string>())
const terminal = new Set(['cancelled'])

/* ---- inline editing state ---- */
const editingTitle = ref<Record<string, string>>({})
const editingInstruction = ref<Record<string, string>>({})
const expandedHistory = ref(new Set<string>())
const expandedError = ref(new Set<string>())
const occurrences = ref<Record<string, Array<{ id: string; status: string; scheduled_at: string; started_at?: string | null; completed_at?: string | null; attempt_count: number; last_error?: string }>>>({})

const orderedJobs = computed(() => [...jobs.value].sort((a, b) => {
  const aTerminal = terminal.has(a.status) ? 1 : 0
  const bTerminal = terminal.has(b.status) ? 1 : 0
  return aTerminal - bTerminal || Date.parse(b.updated_at) - Date.parse(a.updated_at)
}))

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
  // Set placeholder before expanding so the v-for never receives undefined
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
  if (status === 'running') return 'var(--green)'
  if (status === 'failed') return 'var(--red)'
  if (status === 'paused' || status === 'waiting') return 'var(--orange)'
  if (status === 'completed') return 'var(--green)'
  return 'var(--muted)'
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
</script>

<template>
  <main class="arrange-page" :aria-busy="loading">
    <header class="arrange-header">
      <div>
        <button class="text-button" @click="$emit('back')">← 返回</button>
        <h1>安排</h1>
        <p>长期任务，按计划自动执行。</p>
      </div>
      <button class="quiet-button" :disabled="loading" @click="loadJobs">{{ loading ? '刷新中…' : '刷新' }}</button>
    </header>

    <p v-if="loading" class="arrange-loading" role="status">正在读取安排…</p>

    <div v-else-if="error" class="arrange-error" role="alert">
      <span>{{ error }}</span>
      <button type="button" @click="loadJobs">重试</button>
    </div>

    <div v-else-if="orderedJobs.length === 0" class="arrange-empty">
      还没有安排。可以直接告诉 Agent「安排一下……」。
    </div>

    <div v-else class="card-list" role="list">
      <article
        v-for="job in orderedJobs"
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
          <span class="meta-item">项目 <code>{{ (job.project_id || '').slice(0, 8) || '-' }}</code></span>
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
              <span class="history-status" :style="{ color: occ.status === 'completed' ? 'var(--green)' : occ.status === 'failed' ? 'var(--red)' : 'var(--muted)' }">
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
</template>

<style scoped>
.arrange-page { min-height: 100vh; padding: 36px clamp(24px, 6vw, 88px); color: var(--text); background: var(--bg); }
.arrange-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; max-width: 780px; margin: 0 auto 28px; }
h1 { margin: 18px 0 6px; font-size: 30px; letter-spacing: -.025em; } p { margin: 0; } .arrange-header p, .text-button { color: var(--muted); }
button { font: inherit; } .text-button, .quiet-button { border: 0; background: transparent; color: inherit; cursor: pointer; }
.text-button { padding: 0; } .quiet-button { padding: 7px 12px; border: 1px solid var(--line); border-radius: 8px; }

.arrange-loading, .arrange-empty { max-width: 780px; margin-inline: auto; padding: 28px 0; color: var(--muted); }
.arrange-error { max-width: 780px; margin-inline: auto; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 0; color: var(--red); }
.arrange-error button { flex: none; min-height: 36px; padding: 6px 11px; border: 1px solid currentColor; border-radius: 8px; background: transparent; color: inherit; cursor: pointer; }

/* ---- cards ---- */
.card-list { max-width: 780px; margin-inline: auto; display: grid; gap: 16px; }

.arrange-card {
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--panel-2);
}
.card-row { display: flex; align-items: center; gap: 8px; }
.card-row + .card-row { margin-top: 10px; }

/* row 1: title */
.title-row { justify-content: space-between; }
.title-area { min-width: 0; flex: 1; }
.card-title { font-size: 15px; font-weight: 600; cursor: pointer; border-radius: 4px; padding: 1px 4px; margin: -1px -4px; }
.card-title:hover { background: color-mix(in srgb, var(--text) 6%, transparent); }
.card-title:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.title-actions { display: flex; gap: 4px; flex-shrink: 0; }
.action-btn { padding: 4px 8px; border: 0; border-radius: 6px; background: transparent; color: var(--muted); cursor: pointer; font-size: 13px; }
.action-btn:hover { background: color-mix(in srgb, var(--text) 7%, transparent); color: var(--text); }
.action-btn:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.action-btn.danger { color: var(--red); }

/* row 2: instruction */
.instruction-row { flex-wrap: wrap; }
.card-instruction { color: var(--muted); font-size: 13px; cursor: pointer; border-radius: 4px; padding: 2px 4px; margin: -2px -4px; white-space: pre-wrap; }
.card-instruction:hover { background: color-mix(in srgb, var(--text) 5%, transparent); color: var(--text); }
.card-instruction:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

/* row 3+4: meta */
.meta-row, .trigger-row { color: var(--muted); font-size: 13px; }
.meta-item { display: inline-flex; align-items: center; gap: 4px; }
.meta-item.clickable { cursor: pointer; border-radius: 4px; padding: 1px 4px; margin: -1px -4px; }
.meta-item.clickable:hover { background: color-mix(in srgb, var(--text) 5%, transparent); color: var(--text); }
.meta-item.clickable:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.meta-item code { font-size: 12px; color: var(--muted); background: color-mix(in srgb, var(--text) 6%, transparent); border-radius: 4px; padding: 1px 5px; }
.meta-divider { color: var(--faint); }

/* row 5: status */
.status-row { justify-content: space-between; }
.status-label { font-size: 13px; display: inline-flex; align-items: center; gap: 5px; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }

/* inline edit */
.inline-edit { box-sizing: border-box; width: 100%; padding: 4px 6px; border: 1px solid var(--blue); border-radius: 6px; background: var(--bg); color: var(--text); font: inherit; }
.title-edit { font-size: 15px; font-weight: 600; }
.instruction-edit { resize: vertical; min-height: 48px; font-size: 13px; }
.edit-hint { display: flex; gap: 4px; margin-top: 4px; }
.mini-btn { padding: 3px 8px; border: 0; border-radius: 5px; background: var(--blue); color: #101820; cursor: pointer; font-size: 12px; }
.mini-btn:last-child { background: transparent; color: var(--muted); }
.mini-btn:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

/* expand */
.expand-toggle, .error-toggle { padding: 0; border: 0; background: transparent; color: var(--muted); cursor: pointer; font-size: 12px; }
.expand-toggle:hover, .error-toggle:hover { color: var(--text); }
.card-expand { margin-top: 8px; padding: 10px 12px; border-radius: 8px; background: color-mix(in srgb, var(--text) 3%, transparent); font-size: 13px; }

.history-panel { max-height: 200px; overflow-y: auto; }
.history-loading, .history-empty { color: var(--muted); }
.history-item { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
.history-item + .history-item { border-top: 1px solid color-mix(in srgb, var(--text) 5%, transparent); }
.history-time { color: var(--muted); min-width: 140px; font-size: 12px; }
.history-status { font-size: 12px; }
.history-attempts { color: var(--muted); font-size: 11px; }

.error-panel { color: var(--red); white-space: pre-wrap; word-break: break-all; font-size: 12px; }

button:disabled { cursor: default; opacity: .5; }

@media (max-width: 700px) {
  .arrange-page { padding: 24px 18px; }
  .arrange-card { padding: 14px 16px; }
  .title-row { align-items: flex-start; flex-direction: column; gap: 8px; }
  .title-actions { width: 100%; }
  .action-btn { min-height: 36px; }
  .text-button, .quiet-button { min-height: 44px; }
}
</style>