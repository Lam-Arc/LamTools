<template>
  <aside
    v-if="visible"
    class="wf-node-runtime"
    :class="[`state-${state}`, { 'is-collapsed': collapsed }]"
    :aria-label="`${title}运行详情`"
    @pointerdown.stop
    @click.stop
  >
    <button
      type="button"
      class="wf-node-runtime-summary"
      :aria-expanded="collapsed ? 'false' : 'true'"
      :title="collapsed ? '展开运行详情' : '收起运行详情'"
      @click="collapsed = !collapsed"
    >
      <component :is="statusIcon" :size="13" :stroke-width="1.9" :class="{ 'is-spinning': state === 'running' }" aria-hidden="true" />
      <span>{{ stateLabel }}</span>
      <span v-if="artifactItems.length" class="wf-node-runtime-count">{{ artifactItems.length }} 个产物</span>
      <ChevronRight :size="13" :stroke-width="1.8" class="wf-node-runtime-chevron" aria-hidden="true" />
    </button>

    <div v-if="!collapsed" class="wf-node-runtime-body">
      <dl v-if="hasMetadata" class="wf-node-runtime-meta">
        <div v-if="durationLabel"><dt>耗时</dt><dd>{{ durationLabel }}</dd></div>
        <div v-if="runtime.attempts !== undefined"><dt>尝试</dt><dd>{{ runtime.attempts }}</dd></div>
        <div v-if="runtime.cache_status"><dt>缓存</dt><dd>{{ runtime.cache_status }}</dd></div>
      </dl>

      <p v-if="runtime.error" class="wf-node-runtime-error" role="alert">{{ runtime.error }}</p>

      <section v-if="hasValue(runtime.output)" class="wf-node-runtime-section">
        <header><span>{{ outputLabel }}</span><small v-if="state === 'running'">实时</small></header>
        <pre>{{ formatRuntimeValue(runtime.output) }}</pre>
      </section>

      <section v-if="hasValue(runtime.logs)" class="wf-node-runtime-section">
        <header><span>日志</span><small>{{ detailCount(runtime.logs) }}</small></header>
        <pre>{{ formatRuntimeValue(runtime.logs) }}</pre>
      </section>

      <section v-if="hasValue(runtime.tool_calls)" class="wf-node-runtime-section">
        <header><span>工具调用</span><small>{{ detailCount(runtime.tool_calls) }}</small></header>
        <pre>{{ formatRuntimeValue(runtime.tool_calls) }}</pre>
      </section>

      <section v-if="artifactItems.length" class="wf-node-runtime-section">
        <header><span>产物</span><small>{{ artifactItems.length }}</small></header>
        <ul class="wf-node-runtime-artifacts">
          <li v-for="item in artifactItems" :key="item.id">
            <img v-if="item.kind === 'image' && item.previewable" :src="item.value" :alt="item.label" loading="lazy" />
            <a v-else-if="item.linkable" :href="item.value" target="_blank" rel="noreferrer">{{ item.label }}</a>
            <code v-else>{{ item.label }}</code>
          </li>
        </ul>
      </section>

      <HumanTaskPanel
        v-if="pendingTasks.length"
        class="wf-node-runtime-approval"
        :tasks="pendingTasks"
        :selected-task="selectedTask"
        :loading="humanTaskLoading"
        :busy="humanTaskBusy"
        :error="humanTaskError"
        :on-refresh="onRefreshHumanTasks"
        :on-select="onSelectHumanTask"
        :on-complete="onCompleteHumanTask"
      />
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  CheckCircle2,
  ChevronRight,
  Circle,
  CircleSlash2,
  Clock3,
  LoaderCircle,
  XCircle,
  type LucideIcon,
} from 'lucide-vue-next'
import HumanTaskPanel from './HumanTaskPanel.vue'
import type {
  NodeStateStatus,
  WorkflowHumanTask,
  WorkflowNodeState,
  WorkflowRunTimelineItem,
} from './types'

const props = withDefaults(defineProps<{
  nodeId: string
  title: string
  kind: string
  state?: NodeStateStatus
  detail?: WorkflowNodeState | null
  timeline?: WorkflowRunTimelineItem[]
  humanTasks?: WorkflowHumanTask[]
  selectedHumanTask?: WorkflowHumanTask | null
  humanTaskLoading?: boolean
  humanTaskBusy?: boolean
  humanTaskError?: string
  onRefreshHumanTasks?: () => void | Promise<void>
  onSelectHumanTask?: (taskId: string) => void | Promise<void>
  onCompleteHumanTask?: (task: WorkflowHumanTask, decision: string, payload: Record<string, unknown>) => void | Promise<void>
}>(), {
  state: 'idle',
  detail: null,
  timeline: () => [],
  humanTasks: () => [],
  selectedHumanTask: null,
  humanTaskLoading: false,
  humanTaskBusy: false,
  humanTaskError: '',
  onRefreshHumanTasks: undefined,
  onSelectHumanTask: undefined,
  onCompleteHumanTask: undefined,
})

const collapsed = ref(['done', 'skipped', 'cancelled'].includes(props.state))
const pendingTasks = computed(() => props.humanTasks.filter((task) => (
  task.node_id === props.nodeId && String(task.status).toLowerCase() === 'pending'
)))
const selectedTask = computed(() => {
  if (props.selectedHumanTask && pendingTasks.value.some((task) => task.task_id === props.selectedHumanTask?.task_id)) {
    return props.selectedHumanTask
  }
  return pendingTasks.value[0] || null
})
const latestTimeline = computed(() => props.timeline.length ? props.timeline[props.timeline.length - 1] : null)
const runtime = computed<Partial<WorkflowNodeState & WorkflowRunTimelineItem>>(() => {
  const latest = latestTimeline.value || {}
  const detail = props.detail || {}
  return Object.fromEntries(Object.entries({ ...detail, ...latest }).filter(([, value]) => value !== undefined))
})
const visible = computed(() => props.state !== 'idle' || pendingTasks.value.length > 0 || hasRuntimeContent(runtime.value))
const state = computed(() => pendingTasks.value.length ? 'waiting' : props.state)
const stateLabel = computed(() => ({
  running: '运行中', waiting: '等待操作', done: '已完成', error: '失败', skipped: '已跳过', cancelled: '已取消', idle: '运行详情',
}[state.value] || state.value))
const statusIcon = computed<LucideIcon>(() => ({
  running: LoaderCircle,
  waiting: Clock3,
  done: CheckCircle2,
  error: XCircle,
  skipped: CircleSlash2,
  cancelled: XCircle,
  idle: Circle,
}[state.value] || Circle))
const outputLabel = computed(() => ['command', 'python', 'script'].includes(props.kind) ? '输出' : '结果')
const durationLabel = computed(() => formatDuration(runtime.value))
const hasMetadata = computed(() => Boolean(durationLabel.value || runtime.value.attempts !== undefined || runtime.value.cache_status))
const artifactItems = computed(() => collectArtifacts(runtime.value.output))

watch(state, (next, previous) => {
  if (next === 'running' || next === 'waiting' || next === 'error') collapsed.value = false
  else if (previous === 'running' && ['done', 'skipped', 'cancelled'].includes(next)) collapsed.value = true
})

const BLOCKED_OBSERVABILITY_KEYS = /(?:chain[_ -]?of[_ -]?thought|reasoning|internal[_ -]?thought|hidden[_ -]?thought|model[_ -]?analysis)/i

function safeRuntimeValue(value: unknown, depth = 0): unknown {
  if (depth > 5 || value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.slice(0, 80).map((item) => safeRuntimeValue(item, depth + 1))
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .filter(([key]) => !BLOCKED_OBSERVABILITY_KEYS.test(key))
    .slice(0, 80)
    .map(([key, child]) => [key, safeRuntimeValue(child, depth + 1)]))
}

function formatRuntimeValue(value: unknown): string {
  if (value === undefined) return '—'
  if (typeof value === 'string') return value || '—'
  try { return JSON.stringify(safeRuntimeValue(value), null, 2) || '—' } catch { return String(value) }
}

function hasValue(value: unknown): boolean {
  return value !== undefined && value !== null && !(typeof value === 'string' && !value.trim())
}

function hasRuntimeContent(value: Partial<WorkflowNodeState & WorkflowRunTimelineItem>): boolean {
  return Boolean(value.error || hasValue(value.output) || hasValue(value.logs) || hasValue(value.tool_calls))
}

function detailCount(value: unknown): number {
  if (Array.isArray(value)) return value.length
  if (value && typeof value === 'object') return Object.keys(value).length
  return hasValue(value) ? 1 : 0
}

function formatDuration(value: Partial<WorkflowNodeState & WorkflowRunTimelineItem>): string {
  const explicit = Number(value.duration_ms)
  if (Number.isFinite(explicit) && explicit >= 0) return explicit < 1000 ? `${Math.round(explicit)} ms` : `${(explicit / 1000).toFixed(explicit >= 10_000 ? 0 : 1)} s`
  if (!value.started_at || !value.finished_at) return ''
  const elapsed = new Date(value.finished_at).getTime() - new Date(value.started_at).getTime()
  return Number.isFinite(elapsed) && elapsed >= 0 ? (elapsed < 1000 ? `${elapsed} ms` : `${(elapsed / 1000).toFixed(1)} s`) : ''
}

interface RuntimeArtifact { id: string; label: string; value: string; kind: 'image' | 'pdf' | 'file'; previewable: boolean; linkable: boolean }

function collectArtifacts(value: unknown): RuntimeArtifact[] {
  const found = new Map<string, RuntimeArtifact>()
  const visit = (candidate: unknown, key = '', depth = 0): void => {
    if (depth > 5 || candidate === null || candidate === undefined) return
    if (Array.isArray(candidate)) {
      candidate.slice(0, 80).forEach((item, index) => visit(item, `${key}[${index}]`, depth + 1))
      return
    }
    if (typeof candidate === 'object') {
      Object.entries(candidate as Record<string, unknown>).forEach(([childKey, child]) => {
        if (!BLOCKED_OBSERVABILITY_KEYS.test(childKey)) visit(child, childKey, depth + 1)
      })
      return
    }
    if (typeof candidate !== 'string') return
    const raw = candidate.trim()
    const artifactKey = /(?:url|uri|path|file|artifact|attachment|image|pdf)/i.test(key)
    const extension = raw.split(/[?#]/)[0].match(/\.([a-z0-9]{2,8})$/i)?.[1]?.toLowerCase() || ''
    const image = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'avif', 'svg'].includes(extension) || /^data:image\//i.test(raw)
    const pdf = extension === 'pdf'
    if (!artifactKey && !image && !pdf) return
    const linkable = /^(?:https?:|blob:|data:)/i.test(raw)
    const previewable = image && linkable
    const label = key ? `${key}: ${raw}` : raw
    found.set(raw, { id: `${key}:${raw}`, label, value: raw, kind: image ? 'image' : pdf ? 'pdf' : 'file', previewable, linkable })
  }
  visit(value)
  return [...found.values()].slice(0, 24)
}
</script>

<style scoped>
.wf-node-runtime {
  position: absolute;
  top: 0;
  left: calc(100% + var(--space-2));
  width: min(360px, 42vw);
  max-height: min(520px, 66vh);
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  border-radius: 0 var(--radius-lg) var(--radius-lg) 0;
  background: color-mix(in srgb, var(--theme-main-background) 62%, transparent);
  color: var(--theme-main-text);
  box-shadow: var(--shadow-sm);
  -webkit-backdrop-filter: blur(var(--space-4)) saturate(1.24);
  backdrop-filter: blur(var(--space-4)) saturate(1.24);
}
.wf-node-runtime.is-collapsed { width: auto; max-width: 240px; }
.wf-node-runtime-summary { display: flex; align-items: center; width: 100%; min-height: 34px; gap: var(--space-1); padding: var(--space-1) var(--space-2); border: 0; background: transparent; color: inherit; font-size: 11px; font-weight: 650; text-align: left; cursor: pointer; }
.wf-node-runtime-summary:hover { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); }
.wf-node-runtime-summary:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 72%, transparent); outline-offset: -2px; }
.wf-node-runtime-count { margin-left: auto; color: color-mix(in srgb, var(--theme-main-text) 56%, transparent); font-size: 10px; white-space: nowrap; }
.wf-node-runtime-chevron { flex: 0 0 auto; transition: transform var(--dur-fast) var(--ease-out); }
.wf-node-runtime:not(.is-collapsed) .wf-node-runtime-chevron { transform: rotate(90deg); }
.wf-node-runtime.state-running .wf-node-runtime-summary { color: var(--blue); }
.wf-node-runtime.state-waiting .wf-node-runtime-summary { color: var(--orange); }
.wf-node-runtime.state-done .wf-node-runtime-summary { color: var(--green); }
.wf-node-runtime.state-error .wf-node-runtime-summary { color: var(--red); }
.wf-node-runtime-body { display: grid; max-height: calc(min(520px, 66vh) - 34px); gap: var(--space-2); padding: 0 var(--space-2) var(--space-2); overflow: auto; }
.wf-node-runtime-meta { display: flex; flex-wrap: wrap; gap: var(--space-2); margin: 0; padding-top: var(--space-1); }
.wf-node-runtime-meta div { display: grid; gap: 1px; }
.wf-node-runtime-meta dt, .wf-node-runtime-section header, .wf-node-runtime-section small { color: color-mix(in srgb, var(--theme-main-text) 54%, transparent); font-size: 10px; }
.wf-node-runtime-meta dd { margin: 0; font: 10px var(--font-mono, monospace); }
.wf-node-runtime-error { margin: 0; padding: var(--space-2); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--red) 12%, transparent); color: var(--red); font-size: 10px; white-space: pre-wrap; word-break: break-word; }
.wf-node-runtime-section { display: grid; gap: var(--space-1); min-width: 0; }
.wf-node-runtime-section header { display: flex; justify-content: space-between; gap: var(--space-2); }
.wf-node-runtime-section pre { max-height: 210px; margin: 0; padding: var(--space-2); overflow: auto; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-main-sunken-background) 76%, transparent); color: var(--theme-main-text); font: 10px/1.45 var(--font-mono, monospace); white-space: pre-wrap; word-break: break-word; }
.wf-node-runtime-artifacts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-1); margin: 0; padding: 0; list-style: none; }
.wf-node-runtime-artifacts li { min-width: 0; overflow: hidden; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-main-sunken-background) 70%, transparent); }
.wf-node-runtime-artifacts img { display: block; width: 100%; max-height: 160px; object-fit: contain; }
.wf-node-runtime-artifacts a, .wf-node-runtime-artifacts code { display: block; overflow: hidden; padding: var(--space-2); color: inherit; font: 10px/1.35 var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.wf-node-runtime-approval { margin-inline: calc(var(--space-2) * -1); margin-bottom: calc(var(--space-2) * -1); border-top: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent); }
.is-spinning { animation: wf-node-runtime-spin .8s linear infinite; }
@keyframes wf-node-runtime-spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) { .wf-node-runtime { width: min(320px, 72vw); } }
@media (prefers-reduced-motion: reduce) { .wf-node-runtime *, .wf-node-runtime { transition: none; animation: none; } }
</style>
