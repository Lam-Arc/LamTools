<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { CoreArrangeJob } from '../durable/types'

const props = defineProps<{
  listJobs: () => Promise<CoreArrangeJob[]>
  updateJob: (jobId: string, action: 'pause' | 'resume' | 'cancel') => Promise<CoreArrangeJob>
}>()
defineEmits<{ back: [] }>()

const jobs = ref<CoreArrangeJob[]>([])
const loading = ref(false)
const error = ref('')
const busyIds = ref(new Set<string>())
const terminal = new Set(['completed', 'failed', 'cancelled'])

const orderedJobs = computed(() => [...jobs.value].sort((a, b) => {
  const aTerminal = terminal.has(a.status) ? 1 : 0
  const bTerminal = terminal.has(b.status) ? 1 : 0
  return aTerminal - bTerminal || Date.parse(b.updated_at) - Date.parse(a.updated_at)
}))

async function loadJobs() {
  loading.value = true
  error.value = ''
  try { jobs.value = await props.listJobs() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '读取安排失败' }
  finally { loading.value = false }
}

async function changeStatus(job: CoreArrangeJob, action: 'pause' | 'resume' | 'cancel') {
  busyIds.value = new Set([...busyIds.value, job.id])
  error.value = ''
  try {
    const updated = await props.updateJob(job.id, action)
    jobs.value = jobs.value.map(item => item.id === updated.id ? updated : item)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '更新安排失败'
  } finally {
    const next = new Set(busyIds.value)
    next.delete(job.id)
    busyIds.value = next
  }
}

function instruction(job: CoreArrangeJob) { return String(job.payload.message || '未命名安排') }
function formatTime(value: string) {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString() : value || '待定'
}
function schedule(job: CoreArrangeJob) {
  const trigger = job.trigger
  if (trigger.type === 'calendar') {
    return trigger.frequency === 'daily'
      ? `每天 ${trigger.time} · ${trigger.timezone}`
      : `每月 ${trigger.day} 日 ${trigger.time} · ${trigger.timezone}`
  }
  if (trigger.type === 'once') return `单次 · ${String(trigger.local_at || formatTime(String(trigger.run_at || job.next_run_at || '')))}`
  if (trigger.type === 'interval') return `每 ${trigger.every_seconds} 秒`
  if (trigger.type === 'event') return `事件 · ${String(trigger.event_type || '')}`
  return '未知触发方式'
}
function statusLabel(status: CoreArrangeJob['status']) {
  return ({ scheduled: '已安排', waiting: '等待事件', running: '运行中', paused: '已暂停', completed: '已完成', failed: '失败', cancelled: '已取消' } as Record<string, string>)[status] || status
}

onMounted(loadJobs)
</script>

<template>
  <main class="arrange-page" :aria-busy="loading">
    <header class="arrange-header">
      <div>
        <button class="text-button" @click="$emit('back')">← 返回</button>
        <h1>安排</h1>
        <p>查看长期任务、下次运行时间和当前状态。</p>
      </div>
      <button class="quiet-button" :disabled="loading" @click="loadJobs">{{ loading ? '刷新中…' : '刷新' }}</button>
    </header>
    <p v-if="loading" class="arrange-loading" role="status">正在读取安排…</p>
    <div v-else-if="error" class="arrange-error" role="alert">
      <span>{{ error }}</span>
      <button type="button" data-arrange-retry @click="loadJobs">重试</button>
    </div>
    <div v-else-if="orderedJobs.length === 0" class="arrange-empty">还没有安排。可以直接告诉 Agent“安排一下……”。</div>
    <div v-else class="job-list" role="list" aria-label="安排列表">
      <article v-for="job in orderedJobs" :key="job.id" class="job-row" role="listitem">
        <div class="job-main">
          <div class="job-title-line"><strong>{{ instruction(job) }}</strong><span class="job-status" :data-status="job.status">{{ statusLabel(job.status) }}</span></div>
          <div class="job-meta"><span>{{ schedule(job) }}</span><span v-if="job.next_run_at">下次 {{ formatTime(job.next_run_at) }}</span><span>已运行 {{ job.run_count }} 次</span></div>
          <p v-if="job.last_error" class="job-error">{{ job.last_error }}</p>
        </div>
        <div class="job-actions">
          <button v-if="['scheduled', 'waiting', 'running'].includes(job.status)" :disabled="busyIds.has(job.id)" @click="changeStatus(job, 'pause')">暂停</button>
          <button v-if="job.status === 'paused'" :disabled="busyIds.has(job.id)" @click="changeStatus(job, 'resume')">恢复</button>
          <button v-if="!terminal.has(job.status)" class="danger" :disabled="busyIds.has(job.id)" @click="changeStatus(job, 'cancel')">取消</button>
        </div>
      </article>
    </div>
  </main>
</template>

<style scoped>
.arrange-page { min-height: 100vh; padding: 36px clamp(24px, 6vw, 88px); color: var(--text); background: var(--bg); }
.arrange-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; max-width: 1040px; margin: 0 auto 28px; }
h1 { margin: 18px 0 6px; font-size: 30px; letter-spacing: -.025em; } p { margin: 0; } .arrange-header p, .job-meta, .text-button { color: var(--muted); }
button { font: inherit; } .text-button, .quiet-button, .job-actions button { border: 0; background: transparent; color: inherit; cursor: pointer; }
.text-button { padding: 0; } .quiet-button { padding: 7px 12px; border: 1px solid var(--line); border-radius: 8px; }
.job-list, .arrange-empty, .arrange-error, .arrange-loading { max-width: 1040px; margin-inline: auto; } .job-list { border-top: 1px solid var(--line); }
.job-row { display: flex; align-items: center; gap: 24px; padding: 18px 4px; border-bottom: 1px solid var(--line); } .job-main { min-width: 0; flex: 1; }
.job-title-line { display: flex; align-items: center; gap: 10px; } .job-title-line strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.job-status { flex: none; padding: 2px 7px; border-radius: 999px; font-size: 12px; color: var(--muted); background: color-mix(in srgb, var(--text) 7%, transparent); }
.job-status[data-status='running'], .job-status[data-status='scheduled'] { color: var(--blue); }
.job-meta { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 7px; font-size: 13px; } .job-actions { display: flex; gap: 4px; }
.job-actions button { padding: 6px 9px; border-radius: 7px; color: var(--muted); } .job-actions button:hover { background: color-mix(in srgb, var(--text) 7%, transparent); color: var(--text); }
.job-actions button:focus-visible, .quiet-button:focus-visible, .text-button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.danger, .job-error, .arrange-error { color: var(--red); } .job-error { margin-top: 8px; font-size: 13px; } .arrange-empty, .arrange-loading { padding: 28px 0; color: var(--muted); border-top: 1px solid var(--line); }
.arrange-error { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 0; border-top: 1px solid var(--line); }
.arrange-error button { flex: none; min-height: 36px; padding: 6px 11px; border: 1px solid currentColor; border-radius: 8px; background: transparent; color: inherit; cursor: pointer; }
.arrange-error button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
button:disabled { cursor: default; opacity: .5; }
@media (max-width: 700px) { .arrange-page { padding: 24px 18px; } .job-row { align-items: flex-start; flex-direction: column; gap: 10px; } .text-button, .quiet-button, .job-actions button { min-height: 44px; } }
</style>
