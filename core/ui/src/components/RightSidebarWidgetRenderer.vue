<template>
  <div class="right-sidebar-widget-renderer">
    <div v-if="loading" class="right-sidebar-widget-state" role="status" aria-live="polite">
      正在加载…
    </div>
    <div v-else-if="error" class="right-sidebar-widget-state right-sidebar-widget-state--error" role="alert">
      {{ error }}
    </div>
    <component
      :is="component"
      v-else-if="component"
      :widget="entry"
      :snapshot="snapshot"
      :project-id="projectId"
      :session-id="sessionId"
      :request-rpc="requestRpc"
    />
    <template v-else>
      <div
        v-if="snapshot?.message"
        class="right-sidebar-widget-message"
      >{{ snapshot.message }}</div>
      <div
        v-for="(block, index) in snapshot?.blocks || []"
        :key="`${entry.pluginId}:${entry.id}:block:${index}`"
        class="right-sidebar-widget-block"
        :class="`right-sidebar-widget-block--${block.type}`"
      >
        <template v-if="block.type === 'status'">
          <span>{{ block.label || '状态' }}</span>
          <strong :data-state="block.state || snapshot?.state">{{ block.value || snapshot?.state || '未知' }}</strong>
        </template>
        <template v-else-if="block.type === 'metric'">
          <span>{{ block.label || '指标' }}</span>
          <strong>{{ formatValue(block.value) }}</strong>
          <small v-if="block.detail">{{ block.detail }}</small>
        </template>
        <template v-else-if="block.type === 'progress'">
          <div class="right-sidebar-widget-progress-head">
            <span>{{ block.label || '进度' }}</span>
            <strong>{{ progressLabel(block.value, block.max) }}</strong>
          </div>
          <div class="right-sidebar-widget-progress-track" role="progressbar" :aria-valuenow="safeProgress(block.value)" :aria-valuemax="safeMax(block.max)">
            <span :style="{ transform: `scaleX(${progressRatio(block.value, block.max)})` }"></span>
          </div>
          <small v-if="block.detail">{{ block.detail }}</small>
        </template>
        <template v-else-if="block.type === 'list'">
          <span v-if="block.label" class="right-sidebar-widget-list-label">{{ block.label }}</span>
          <ul>
            <li v-for="(item, itemIndex) in block.items || []" :key="`${index}:${itemIndex}`">
              <template v-if="typeof item === 'object' && item !== null">
                <strong>{{ formatValue(item.label) }}</strong>
                <span>{{ formatValue(item.value) }}</span>
                <small v-if="item.detail">{{ item.detail }}</small>
              </template>
              <template v-else>{{ formatValue(item) }}</template>
            </li>
          </ul>
        </template>
        <template v-else>
          <span v-if="block.label">{{ block.label }}</span>
          <span>{{ 'text' in block && block.text ? block.text : formatValue('value' in block ? block.value : '') }}</span>
        </template>
      </div>
      <div v-if="!loading && !error && !snapshot?.blocks?.length && !snapshot?.message" class="right-sidebar-widget-empty">
        暂无可用数据
      </div>
      <div v-if="actions.length" class="right-sidebar-widget-actions">
        <button
          v-for="action in actions"
          :key="action.id"
          type="button"
          class="right-sidebar-widget-action"
          :disabled="invoking === action.id || action.enabled === false"
          @click="invoke(action)"
        >
          {{ invoking === action.id ? '处理中…' : action.title }}
        </button>
      </div>
    </template>

    <CoreConfirmDialog
      :open="Boolean(pendingDangerous)"
      :title="pendingDangerous?.title || '执行动作？'"
      @cancel="resolveDangerous(false)"
      @confirm="resolveDangerous(true)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Component } from 'vue'
import { getPluginWidget, invokePluginWidget } from '../plugins/api'
import { getWidget } from '../plugins/registry'
import CoreConfirmDialog from './CoreConfirmDialog.vue'
import type {
  PluginWidgetEntry,
  RightSidebarRpc,
  RightSidebarWidgetAction,
  RightSidebarWidgetSnapshot,
} from '../right-sidebar/types'

const props = withDefaults(defineProps<{
  entry: PluginWidgetEntry
  snapshot?: RightSidebarWidgetSnapshot | null
  projectId?: string | null
  workRoot?: string | null
  sessionId?: string | null
  requestRpc?: RightSidebarRpc
}>(), {
  snapshot: null,
  projectId: null,
  workRoot: null,
  sessionId: null,
  requestRpc: undefined,
})

const loading = ref(false)
const error = ref('')
const snapshot = ref<RightSidebarWidgetSnapshot | null>(props.snapshot || null)
const component = ref<Component | null>(null)
const invoking = ref('')
let revision = 0

type SnapshotActionState = {
  id?: unknown
  enabled?: unknown
}

type RenderedWidgetAction = RightSidebarWidgetAction & {
  /** Runtime state is the only action field a snapshot may contribute. */
  enabled?: boolean
}

const actions = computed<RenderedWidgetAction[]>(() => {
  // The backend descriptor is the security and presentation authority for
  // actions.  Snapshots may only report runtime state (currently `enabled`),
  // so a plugin cannot replace a dangerous action with a benign-looking stub
  // or smuggle in a blank label through snapshot data.
  const snapshotStates = new Map<string, SnapshotActionState>()
  for (const candidate of snapshot.value?.actions || []) {
    if (!candidate || typeof candidate !== 'object') continue
    const state = candidate as SnapshotActionState
    const id = typeof state.id === 'string' ? state.id.trim() : ''
    if (id) snapshotStates.set(id, state)
  }

  const descriptorActions = Array.isArray(props.entry.actions) ? props.entry.actions : []
  return descriptorActions.flatMap((candidate) => {
    if (!candidate || typeof candidate !== 'object') return []
    const action = candidate as RightSidebarWidgetAction
    const id = typeof action.id === 'string' ? action.id.trim() : ''
    const title = typeof action.title === 'string' ? action.title.trim() : ''
    if (!id || !title) return []
    const rendered: RenderedWidgetAction = { ...action, id, title }
    const state = snapshotStates.get(id)
    if (typeof state?.enabled === 'boolean') rendered.enabled = state.enabled
    return [rendered]
  })
})

function normalizeSnapshot(value: unknown): RightSidebarWidgetSnapshot | null {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : null
  const candidate = raw && raw.snapshot && typeof raw.snapshot === 'object'
    ? raw.snapshot
    : raw && raw.result && typeof raw.result === 'object'
      ? raw.result
      : raw && raw.widget && typeof raw.widget === 'object'
        ? raw.widget
        : raw
  if (!candidate || typeof candidate !== 'object') return null
  const parsed = candidate as RightSidebarWidgetSnapshot
  const version = parsed.schemaVersion ?? parsed.schema_version
  if (version !== undefined && version !== 1) return null
  const blocks = Array.isArray(parsed.blocks)
    ? parsed.blocks.filter((block) => block && typeof block === 'object' && typeof (block as { type?: unknown }).type === 'string')
    : []
  return { ...parsed, schemaVersion: version ?? 1, blocks }
}

async function load(): Promise<void> {
  const current = ++revision
  component.value = null
  error.value = ''
  snapshot.value = normalizeSnapshot(props.snapshot)
  const registered = getWidget(props.entry.id, props.entry.pluginId)
  const loader = registered?.load
  if (props.entry.renderer === 'component' && loader) {
    loading.value = true
    try {
      const loaded = await loader()
      if (current !== revision) return
      component.value = 'default' in loaded ? loaded.default : loaded
    } catch (cause) {
      if (current !== revision) return
      error.value = `加载 ${props.entry.title} 失败：${cause instanceof Error ? cause.message : String(cause)}`
    } finally {
      if (current === revision) loading.value = false
    }
  }

  // A supplied snapshot is authoritative for this render.  Fetch a fresh
  // snapshot when the backend descriptor explicitly advertises one.  Older
  // descriptors predate `hasSnapshot`, so an operation name remains a
  // capability fallback only when that boolean is absent.  The facade owns
  // operation resolution; the UI must not require the operation name itself.
  const snapshotOperation = props.entry.snapshotOperation || props.entry.snapshot_operation
  const hasSnapshot = props.entry.hasSnapshot ?? Boolean(snapshotOperation)
  if (!snapshot.value && props.requestRpc && hasSnapshot) {
    loading.value = true
    try {
      const result = await getPluginWidget(props.requestRpc, {
        pluginId: props.entry.pluginId,
        widgetId: props.entry.id,
        projectId: props.projectId,
        workRoot: props.workRoot,
        sessionId: props.sessionId,
      })
      if (current !== revision) return
      snapshot.value = normalizeSnapshot(result)
      if (!snapshot.value && !component.value) error.value = '插件未返回有效数据'
    } catch (cause) {
      if (current !== revision) return
      // Missing optional plugin operations are a disabled/empty state, not a
      // fatal host error.  Keep the message actionable but concise.
      error.value = `暂不可用：${cause instanceof Error ? cause.message : String(cause)}`
    } finally {
      if (current === revision) loading.value = false
    }
  }
}

function formatValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return '—'
  if (typeof value === 'object') {
    try { return JSON.stringify(value) } catch { return '—' }
  }
  return String(value)
}

function safeProgress(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, number) : 0
}

function safeMax(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number : 100
}

function progressRatio(value: unknown, max: unknown): number {
  return Math.min(1, safeProgress(value) / safeMax(max))
}

function progressLabel(value: unknown, max: unknown): string {
  return `${Math.round(progressRatio(value, max) * 100)}%`
}

/** 危险动作的确认：等一次用户回答（应用内胶囊，不用系统弹窗）。 */
const pendingDangerous = ref<RightSidebarWidgetAction | null>(null)
let dangerousResolver: ((confirmed: boolean) => void) | null = null

function askDangerous(action: RightSidebarWidgetAction): Promise<boolean> {
  pendingDangerous.value = action
  return new Promise<boolean>(resolve => { dangerousResolver = resolve })
}

function resolveDangerous(confirmed: boolean): void {
  pendingDangerous.value = null
  dangerousResolver?.(confirmed)
  dangerousResolver = null
}

async function invoke(action: RightSidebarWidgetAction): Promise<void> {
  if (!props.requestRpc || invoking.value) return
  if ((action as RenderedWidgetAction).enabled === false) return
  if (action.dangerous && !(await askDangerous(action))) return
  invoking.value = action.id
  error.value = ''
  try {
    const idempotencyKey = action.mutates ? createIdempotencyKey() : undefined
    const result = await invokePluginWidget(props.requestRpc, {
      pluginId: props.entry.pluginId,
      widgetId: props.entry.id,
      actionId: action.id,
      projectId: props.projectId,
      workRoot: props.workRoot,
      sessionId: props.sessionId,
      input: {},
      confirmed: action.dangerous === true,
      idempotencyKey,
    })
    const next = normalizeSnapshot(result)
    if (next) snapshot.value = next
  } catch (cause) {
    error.value = `操作失败：${cause instanceof Error ? cause.message : String(cause)}`
  } finally {
    invoking.value = ''
  }
}

function createIdempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  return `widget-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

watch(
  () => [
    props.entry.pluginId,
    props.entry.id,
    props.entry.renderer,
    props.entry.hasSnapshot,
    props.entry.snapshotOperation,
    props.entry.snapshot_operation,
    props.projectId,
    props.workRoot,
    props.sessionId,
    props.snapshot,
  ],
  () => { void load() },
  { immediate: true },
)

watch(() => props.snapshot, (value) => {
  if (value) snapshot.value = normalizeSnapshot(value)
})
</script>

<style scoped>
.right-sidebar-widget-renderer {
  display: grid;
  gap: var(--space-2);
  min-width: 0;
  color: var(--theme-backdrop-text);
  font-size: 12px;
  line-height: 1.45;
}
.right-sidebar-widget-state,
.right-sidebar-widget-empty,
.right-sidebar-widget-message {
  color: color-mix(in srgb, var(--theme-backdrop-text) 58%, transparent);
}
.right-sidebar-widget-state--error { color: color-mix(in srgb, var(--red) 70%, var(--theme-backdrop-text) 30%); }
.right-sidebar-widget-block { min-width: 0; }
.right-sidebar-widget-block--status,
.right-sidebar-widget-block--metric,
.right-sidebar-widget-progress-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
}
.right-sidebar-widget-block span,
.right-sidebar-widget-block small { color: color-mix(in srgb, var(--theme-backdrop-text) 58%, transparent); }
.right-sidebar-widget-block strong { color: var(--theme-backdrop-text); font-weight: 650; }
.right-sidebar-widget-block strong[data-state="warning"] { color: var(--orange); }
.right-sidebar-widget-block strong[data-state="error"] { color: var(--red); }
.right-sidebar-widget-block strong[data-state="busy"] { color: var(--blue); }
.right-sidebar-widget-block small { display: block; margin-top: var(--space-1); }
.right-sidebar-widget-list-label { display: block; margin-bottom: var(--space-1); }
.right-sidebar-widget-block ul { display: grid; gap: var(--space-1); margin: 0; padding: 0; list-style: none; }
.right-sidebar-widget-block li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--space-2); }
.right-sidebar-widget-block li small { grid-column: 1 / -1; margin-top: calc(-1 * var(--space-1)); }
.right-sidebar-widget-progress-track { height: 4px; overflow: hidden; margin-top: var(--space-1); background: color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent); }
.right-sidebar-widget-progress-track span { display: block; height: 100%; background: var(--blue); transform-origin: left; transition: transform var(--dur-base) var(--ease-out); }
.right-sidebar-widget-actions { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.right-sidebar-widget-action { min-height: 30px; padding: 0 var(--space-2); border: 1px solid color-mix(in srgb, var(--theme-control-text) 16%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); font-size: 12px; }
.right-sidebar-widget-action:hover { background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), var(--theme-control-background)); }
.right-sidebar-widget-action:active { background: color-mix(in srgb, var(--theme-control-text) var(--alpha-active), var(--theme-control-background)); }
.right-sidebar-widget-action:disabled { opacity: .45; cursor: default; }
@media (prefers-reduced-motion: reduce) { .right-sidebar-widget-progress-track span { transition: none; } }
</style>
