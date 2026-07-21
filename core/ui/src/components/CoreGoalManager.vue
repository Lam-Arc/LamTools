<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { CoreGoal } from '../durable/types'

const props = defineProps<{
  listGoals: () => Promise<CoreGoal[]>
  updateGoal: (goalId: string, status: string, reason?: string) => Promise<CoreGoal>
}>()
defineEmits<{ back: [] }>()

const goals = ref<CoreGoal[]>([])
const loading = ref(false)
const error = ref('')
const busyIds = ref(new Set<string>())
const terminal = new Set(['completed', 'failed', 'cancelled'])

const orderedGoals = computed(() => [...goals.value].sort((a, b) => {
  const aTerminal = terminal.has(a.status) ? 1 : 0
  const bTerminal = terminal.has(b.status) ? 1 : 0
  return aTerminal - bTerminal || Date.parse(b.updated_at) - Date.parse(a.updated_at)
}))

async function loadGoals() {
  loading.value = true
  error.value = ''
  try { goals.value = await props.listGoals() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : '读取目标失败' }
  finally { loading.value = false }
}

async function changeStatus(goal: CoreGoal, status: string) {
  busyIds.value = new Set([...busyIds.value, goal.id])
  error.value = ''
  try {
    const updated = await props.updateGoal(goal.id, status)
    goals.value = goals.value.map(item => item.id === updated.id ? updated : item)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '更新目标失败'
  } finally {
    const next = new Set(busyIds.value)
    next.delete(goal.id)
    busyIds.value = next
  }
}

function formatTime(value: string) {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString() : value || ''
}
function statusLabel(status: CoreGoal['status']) {
  return ({ pending: '待开始', active: '进行中', blocked: '已暂停', completed: '已完成', failed: '失败', cancelled: '已取消' } as Record<string, string>)[status] || status
}
function threadLabel(goal: CoreGoal) {
  return goal.thread_id ? goal.thread_id.slice(0, 16) : '-'
}

onMounted(loadGoals)
</script>

<template>
  <main class="goal-page" :aria-busy="loading">
    <header class="goal-header">
      <div>
        <button class="text-button" @click="$emit('back')">← 返回</button>
        <h1>目标</h1>
        <p>查看长期目标、状态和执行进度。</p>
      </div>
      <button class="quiet-button" :disabled="loading" @click="loadGoals">{{ loading ? '刷新中…' : '刷新' }}</button>
    </header>
    <p v-if="loading" class="goal-loading" role="status">正在读取目标…</p>
    <div v-else-if="error" class="goal-error" role="alert">
      <span>{{ error }}</span>
      <button type="button" data-goal-retry @click="loadGoals">重试</button>
    </div>
    <div v-else-if="orderedGoals.length === 0" class="goal-empty">还没有目标。在会话中使用 --goal-id 绑定目标后会自动创建。</div>
    <div v-else class="goal-list" role="list" aria-label="目标列表">
      <article v-for="goal in orderedGoals" :key="goal.id" class="goal-row" role="listitem">
        <div class="goal-main">
          <div class="goal-title-line"><strong>{{ goal.objective }}</strong><span class="goal-status" :data-status="goal.status">{{ statusLabel(goal.status) }}</span></div>
          <div class="goal-meta"><span>会话 {{ threadLabel(goal) }}</span><span v-if="goal.created_at">创建于 {{ formatTime(goal.created_at) }}</span><span v-if="goal.updated_at && goal.updated_at !== goal.created_at">更新于 {{ formatTime(goal.updated_at) }}</span></div>
          <p v-if="goal.status_reason" class="goal-reason">{{ goal.status_reason }}</p>
        </div>
        <div class="goal-actions">
          <button v-if="goal.status === 'pending'" :disabled="busyIds.has(goal.id)" @click="changeStatus(goal, 'active')">激活</button>
          <button v-if="goal.status === 'active'" :disabled="busyIds.has(goal.id)" @click="changeStatus(goal, 'blocked')">暂停</button>
          <button v-if="goal.status === 'blocked'" :disabled="busyIds.has(goal.id)" @click="changeStatus(goal, 'active')">恢复</button>
          <button v-if="goal.status === 'active'" :disabled="busyIds.has(goal.id)" @click="changeStatus(goal, 'completed')">完成</button>
          <button v-if="!terminal.has(goal.status)" class="danger" :disabled="busyIds.has(goal.id)" @click="changeStatus(goal, 'cancelled')">取消</button>
        </div>
      </article>
    </div>
  </main>
</template>

<style scoped>
.goal-page { min-height: 100vh; padding: 36px clamp(24px, 6vw, 88px); color: var(--text); background: var(--bg); }
.goal-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; max-width: 1040px; margin: 0 auto 28px; }
h1 { margin: 18px 0 6px; font-size: 30px; letter-spacing: -.025em; } p { margin: 0; } .goal-header p, .goal-meta, .text-button { color: var(--muted); }
button { font: inherit; } .text-button, .quiet-button, .goal-actions button { border: 0; background: transparent; color: inherit; cursor: pointer; }
.text-button { padding: 0; } .quiet-button { padding: 7px 12px; border: 1px solid var(--line); border-radius: 8px; }
.goal-list, .goal-empty, .goal-error, .goal-loading { max-width: 1040px; margin-inline: auto; } .goal-list { border-top: 1px solid var(--line); }
.goal-row { display: flex; align-items: center; gap: 24px; padding: 18px 4px; border-bottom: 1px solid var(--line); } .goal-main { min-width: 0; flex: 1; }
.goal-title-line { display: flex; align-items: center; gap: 10px; } .goal-title-line strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.goal-status { flex: none; padding: 2px 7px; border-radius: 999px; font-size: 12px; color: var(--muted); background: color-mix(in srgb, var(--text) 7%, transparent); }
.goal-status[data-status='active'] { color: var(--blue); }
.goal-status[data-status='blocked'] { color: var(--orange); }
.goal-meta { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 7px; font-size: 13px; } .goal-actions { display: flex; gap: 4px; }
.goal-actions button { padding: 6px 9px; border-radius: 7px; color: var(--muted); } .goal-actions button:hover { background: color-mix(in srgb, var(--text) 7%, transparent); color: var(--text); }
.goal-actions button:focus-visible, .quiet-button:focus-visible, .text-button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.danger, .goal-reason, .goal-error { color: var(--red); } .goal-reason { margin-top: 8px; font-size: 13px; } .goal-empty, .goal-loading { padding: 28px 0; color: var(--muted); border-top: 1px solid var(--line); }
.goal-error { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 0; border-top: 1px solid var(--line); }
.goal-error button { flex: none; min-height: 36px; padding: 6px 11px; border: 1px solid currentColor; border-radius: 8px; background: transparent; color: inherit; cursor: pointer; }
.goal-error button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
button:disabled { cursor: default; opacity: .5; }
@media (max-width: 700px) { .goal-page { padding: 24px 18px; } .goal-row { align-items: flex-start; flex-direction: column; gap: 10px; } .text-button, .quiet-button, .goal-actions button { min-height: 44px; } }
</style>
