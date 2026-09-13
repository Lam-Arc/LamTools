<template>
  <section class="wf-queue-panel" aria-label="工作流队列与历史">
    <header class="wf-queue-head">
      <div>
        <h3>队列与历史</h3>
        <span class="wf-queue-summary">排队 {{ items.length }} · 历史 {{ history.length }}</span>
      </div>
      <button type="button" class="wf-queue-refresh" :disabled="loading" aria-label="刷新队列" title="刷新" @click="refresh">↻</button>
    </header>
    <div class="wf-queue-tabs" role="tablist" aria-label="队列视图">
      <button type="button" role="tab" :aria-selected="tab === 'queue'" :class="{ active: tab === 'queue' }" @click="tab = 'queue'">当前队列</button>
      <button type="button" role="tab" :aria-selected="tab === 'history'" :class="{ active: tab === 'history' }" @click="tab = 'history'">运行历史</button>
    </div>
    <div class="wf-queue-actions">
      <button type="button" class="wf-queue-primary" :disabled="loading || disabled" @click="enqueue">加入队列</button>
      <button type="button" class="wf-queue-danger" :disabled="loading || !history.length" @click="requestClear(false)">清理历史</button>
      <button type="button" class="wf-queue-danger wf-queue-danger-muted" :disabled="loading || (!items.length && !history.length)" @click="requestClear(true)">清空全部</button>
    </div>
    <div v-if="pendingClear !== null" class="wf-queue-confirm" role="alertdialog" aria-label="确认清理队列">
      <p>此操作不可撤销，将{{ pendingClear ? '删除全部队列项和历史' : '删除已结束历史' }}。</p>
      <div>
        <button type="button" @click="pendingClear = null">取消</button>
        <button type="button" class="wf-queue-danger" @click="confirmClear">确认清理</button>
      </div>
    </div>
    <ul v-if="visibleItems.length" class="wf-queue-list" aria-live="polite">
      <li v-for="item in visibleItems" :key="item.queue_id || item.run_id" class="wf-queue-item" :class="{ selected: selectedId === item.queue_id }">
        <button type="button" class="wf-queue-item-main" @click="inspect(item)">
          <span class="wf-queue-status" :class="`status-${item.status}`" aria-hidden="true"></span>
          <span class="wf-queue-item-copy">
            <strong>{{ item.run_id || item.queue_id || '未命名运行' }}</strong>
            <small>{{ statusLabel(item.status) }} · 优先级 {{ item.priority }} · {{ formatTimestamp(item.created_at) }}</small>
          </span>
          <span class="wf-queue-chevron" aria-hidden="true">›</span>
        </button>
        <button v-if="canCancel(item)" type="button" class="wf-queue-cancel" :aria-label="`取消运行 ${item.run_id || item.queue_id}`" @click="cancel(item)">取消</button>
      </li>
    </ul>
    <p v-else class="wf-queue-empty">{{ tab === 'queue' ? '当前没有排队运行' : '还没有运行历史' }}</p>
    <article v-if="selected" class="wf-queue-detail" aria-label="队列运行详情">
      <header><strong>运行详情</strong><button type="button" class="wf-queue-close" aria-label="关闭详情" @click="selectedId = ''">×</button></header>
      <dl>
        <div><dt>状态</dt><dd :class="`status-text-${selected.status}`">{{ statusLabel(selected.status) }}</dd></div>
        <div><dt>队列 ID</dt><dd><code>{{ selected.queue_id || '—' }}</code></dd></div>
        <div><dt>运行 ID</dt><dd><code>{{ selected.run_id || '—' }}</code></dd></div>
        <div><dt>优先级</dt><dd>{{ selected.priority ?? 0 }}</dd></div>
        <div><dt>开始</dt><dd>{{ formatTimestamp(selected.started_at) }}</dd></div>
        <div><dt>结束</dt><dd>{{ formatTimestamp(selected.finished_at) }}</dd></div>
      </dl>
      <p v-if="selected.error" class="wf-queue-error" role="alert">{{ selected.error }}</p>
      <details v-if="cacheEntries.length" open>
        <summary>缓存（{{ cacheEntries.length }}）</summary>
        <ul class="wf-queue-cache-list">
          <li v-for="entry in cacheEntries" :key="entry.nodeId"><span>{{ entry.nodeId }}</span><strong :class="`cache-${entry.status}`">{{ entry.status }}</strong><code>{{ entry.key || '—' }}</code></li>
        </ul>
      </details>
      <details v-if="selected.result" open>
        <summary>运行结果</summary>
        <pre>{{ formatValue(selected.result.output) }}</pre>
      </details>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { WorkflowCacheFact, WorkflowQueueItem, WorkflowQueueStatus } from './types'

const props = withDefaults(defineProps<{
  items?: WorkflowQueueItem[]
  history?: WorkflowQueueItem[]
  selectedItem?: WorkflowQueueItem | null
  loading?: boolean
  disabled?: boolean
  onRefresh?: () => void | Promise<void>
  onEnqueue?: () => void | Promise<void>
  onCancel?: (item: WorkflowQueueItem) => void | Promise<void>
  onInspect?: (item: WorkflowQueueItem) => void | Promise<void>
  onClear?: (all: boolean) => void | Promise<void>
}>(), {
  items: () => [], history: () => [], selectedItem: null, loading: false, disabled: false,
  onRefresh: undefined, onEnqueue: undefined, onCancel: undefined, onInspect: undefined, onClear: undefined,
})

const tab = ref<'queue' | 'history'>('queue')
const pendingClear = ref<boolean | null>(null)
const selectedId = ref('')
const selected = computed(() => props.selectedItem && selectedId.value && props.selectedItem.queue_id === selectedId.value ? props.selectedItem : null)
const visibleItems = computed(() => tab.value === 'queue' ? props.items : props.history)
const cacheEntries = computed(() => {
  const cache = props.selectedItem?.result?.cache || {}
  return Object.entries(cache).map(([nodeId, fact]) => ({ nodeId, status: cacheLabel(fact), key: fact.key || '' }))
})

function refresh(): void { void props.onRefresh?.() }
function enqueue(): void { void props.onEnqueue?.() }
function cancel(item: WorkflowQueueItem): void { void props.onCancel?.(item) }
function inspect(item: WorkflowQueueItem): void { selectedId.value = item.queue_id; void props.onInspect?.(item) }
function requestClear(all: boolean): void { pendingClear.value = all }
function confirmClear(): void { const all = pendingClear.value === true; pendingClear.value = null; void props.onClear?.(all) }
function canCancel(item: WorkflowQueueItem): boolean { return item.status === 'queued' || item.status === 'running' || item.status === 'paused' }

function statusLabel(status: WorkflowQueueStatus): string {
  return ({ queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消', paused: '已暂停' } as Record<WorkflowQueueStatus, string>)[status] || status
}
function cacheLabel(fact: WorkflowCacheFact): string {
  const value = String(fact.status || (fact.hit ? 'hit' : fact.miss ? 'miss' : 'bypass')).toLowerCase()
  return value === 'hit' ? '命中' : value === 'miss' ? '未命中' : value === 'bypass' ? '跳过' : '未知'
}
function formatValue(value: unknown): string {
  if (value === undefined || value === null) return '—'
  if (typeof value === 'string') return value || '—'
  try { return JSON.stringify(value, null, 2) || '—' } catch { return String(value) }
}
function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
</script>

<style scoped>
.wf-queue-panel { display: grid; gap: var(--space-2); padding: var(--space-3); border-bottom: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent); color: var(--theme-backdrop-text); }
.wf-queue-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.wf-queue-head h3 { margin: 0; font-size: 12px; font-weight: 700; }
.wf-queue-summary { display: block; margin-top: 2px; color: color-mix(in srgb, var(--theme-backdrop-text) 46%, transparent); font-size: 10px; }
.wf-queue-refresh, .wf-queue-close { min-width: 28px; min-height: 28px; border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text) 66%, transparent); cursor: pointer; font-size: 17px; }
.wf-queue-refresh:hover:not(:disabled), .wf-queue-close:hover { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); color: var(--theme-backdrop-text); }
.wf-queue-refresh:disabled { opacity: .4; cursor: default; }
.wf-queue-tabs { display: flex; gap: var(--space-1); }
.wf-queue-tabs button { flex: 1 1 0; min-height: 28px; border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text) 58%, transparent); cursor: pointer; font-size: 10px; }
.wf-queue-tabs button:hover, .wf-queue-tabs button.active { background: color-mix(in srgb, var(--blue) 18%, transparent); color: var(--theme-backdrop-text); }
.wf-queue-actions { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.wf-queue-actions button, .wf-queue-confirm button { min-height: 28px; border: 0; border-radius: var(--radius-sm); padding: 0 var(--space-2); cursor: pointer; font-size: 10px; }
.wf-queue-primary { background: var(--theme-control-background); color: var(--theme-control-text); font-weight: 650; }
.wf-queue-primary:hover:not(:disabled) { filter: brightness(.94); }
.wf-queue-danger { background: var(--red); color: var(--theme-control-text); font-weight: 650; }
.wf-queue-danger-muted { background: color-mix(in srgb, var(--red) 18%, transparent); color: var(--red); }
.wf-queue-actions button:disabled { opacity: .4; cursor: default; }
.wf-queue-confirm { display: grid; gap: var(--space-2); padding: var(--space-2); border: 1px solid color-mix(in srgb, var(--orange) 40%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--orange) 8%, transparent); }
.wf-queue-confirm p { margin: 0; color: color-mix(in srgb, var(--theme-backdrop-text) 75%, transparent); font-size: 10px; line-height: 1.4; }
.wf-queue-confirm > div { display: flex; justify-content: flex-end; gap: var(--space-1); }
.wf-queue-confirm button:first-child { background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text) 72%, transparent); }
.wf-queue-list { display: grid; gap: var(--space-1); margin: 0; padding: 0; list-style: none; }
.wf-queue-item { display: flex; min-width: 0; align-items: stretch; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-backdrop-text) 4%, transparent); }
.wf-queue-item.selected { background: color-mix(in srgb, var(--blue) 14%, transparent); }
.wf-queue-item-main { flex: 1 1 auto; min-width: 0; display: flex; align-items: center; gap: var(--space-2); border: 0; background: transparent; color: var(--theme-backdrop-text); padding: var(--space-1) var(--space-2); text-align: left; cursor: pointer; }
.wf-queue-item-main:hover, .wf-queue-item-main:focus-visible { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); outline: 0; }
.wf-queue-status { flex: 0 0 auto; width: 7px; height: 7px; border-radius: 50%; background: color-mix(in srgb, var(--theme-backdrop-text) 42%, transparent); }
.wf-queue-status.status-queued, .wf-queue-status.status-paused { background: var(--orange); }
.wf-queue-status.status-running { background: var(--blue); animation: wf-queue-pulse 1.3s ease-in-out infinite; }
.wf-queue-status.status-completed { background: var(--green); }
.wf-queue-status.status-failed { background: var(--red); }
.wf-queue-item-copy { min-width: 0; display: grid; gap: 2px; }
.wf-queue-item-copy strong, .wf-queue-item-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wf-queue-item-copy strong { font-size: 10px; font-weight: 600; }
.wf-queue-item-copy small { color: color-mix(in srgb, var(--theme-backdrop-text) 48%, transparent); font-size: 9px; }
.wf-queue-chevron { margin-left: auto; color: color-mix(in srgb, var(--theme-backdrop-text) 42%, transparent); font-size: 16px; }
.wf-queue-cancel { flex: 0 0 auto; border: 0; border-left: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 9%, transparent); background: transparent; color: var(--red); padding: 0 var(--space-2); cursor: pointer; font-size: 10px; }
.wf-queue-cancel:hover { background: color-mix(in srgb, var(--red) var(--alpha-hover), transparent); }
.wf-queue-empty { margin: 0; color: color-mix(in srgb, var(--theme-backdrop-text) 42%, transparent); font-size: 11px; }
.wf-queue-detail { display: grid; gap: var(--space-2); margin-top: var(--space-1); padding-top: var(--space-2); border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent); }
.wf-queue-detail > header { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); font-size: 11px; }
.wf-queue-detail dl { display: grid; gap: var(--space-1); margin: 0; }
.wf-queue-detail dl > div { display: flex; justify-content: space-between; gap: var(--space-2); font-size: 10px; }
.wf-queue-detail dt { color: color-mix(in srgb, var(--theme-backdrop-text) 48%, transparent); }
.wf-queue-detail dd { margin: 0; text-align: right; overflow-wrap: anywhere; }
.wf-queue-detail code, .wf-queue-cache-list code { color: color-mix(in srgb, var(--theme-backdrop-text) 60%, transparent); font: 9px var(--font-mono); }
.wf-queue-error { margin: 0; color: var(--red); font-size: 10px; white-space: pre-wrap; }
.wf-queue-detail summary { color: color-mix(in srgb, var(--theme-backdrop-text) 58%, transparent); cursor: pointer; font-size: 10px; }
.wf-queue-detail pre { max-height: 140px; overflow: auto; margin: 0; padding: var(--space-2); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-backdrop-background) 80%, var(--theme-main-background)); font: 9px/1.4 var(--font-mono); white-space: pre-wrap; word-break: break-word; }
.wf-queue-cache-list { display: grid; gap: var(--space-1); margin: var(--space-1) 0 0; padding: 0; list-style: none; }
.wf-queue-cache-list li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--space-1); align-items: baseline; font-size: 10px; }
.wf-queue-cache-list li code { grid-column: 1 / -1; overflow-wrap: anywhere; }
.cache-命中 { color: var(--green); }.cache-未命中 { color: var(--orange); }.cache-跳过 { color: color-mix(in srgb, var(--theme-backdrop-text) 60%, transparent); }
.status-text-running { color: var(--blue); }.status-text-completed { color: var(--green); }.status-text-failed { color: var(--red); }.status-text-queued, .status-text-paused { color: var(--orange); }
@keyframes wf-queue-pulse { 50% { opacity: .45; } }
@media (max-width: 640px) { .wf-queue-tabs button, .wf-queue-actions button, .wf-queue-refresh, .wf-queue-close { min-height: 44px; } .wf-queue-cancel { min-width: 56px; } }
@media (prefers-reduced-motion: reduce) { .wf-queue-status.status-running { animation: none; } .wf-queue-panel *, .wf-queue-panel { transition: none; } }
</style>
