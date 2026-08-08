<template>
  <section class="core-session-rollback" aria-labelledby="core-session-rollback-title">
    <header class="rollback-header">
      <div class="rollback-title-row">
        <h3 id="core-session-rollback-title">回退</h3>
        <span class="rollback-count" data-checkpoint-count>{{ nodes.length }} 个节点</span>
      </div>
      <div class="rollback-header-actions">
        <button
          type="button"
          class="quiet-action"
          data-save-checkpoint
          :disabled="loading || busy || activeTurn"
          title="保存当前状态"
          @click="saveCheckpoint"
        >{{ busyAction === 'save' ? '保存中…' : '保存' }}</button>
        <button
          type="button"
          class="icon-action"
          :disabled="loading || busy"
          aria-label="刷新存档节点图"
          title="刷新节点"
          @click="loadGraph"
        >↻</button>
      </div>
    </header>

    <p v-if="activeTurn" class="rollback-notice" data-active-turn-notice>
      任务运行中：仅文件可恢复；恢复对话需先停止任务。
    </p>

    <div v-if="notice" class="rollback-result" role="status" aria-live="polite">
      <span>{{ notice }}</span>
    </div>

    <div v-if="error" class="rollback-error" role="alert">
      <span>{{ error }}</span>
      <button
        v-if="loadFailed"
        type="button"
        class="quiet-action"
        data-retry-checkpoints
        :disabled="loading"
        @click="loadGraph"
      >重试</button>
    </div>

    <div
      v-if="loading && nodes.length === 0"
      class="rollback-loading"
      aria-label="正在加载存档节点图"
      aria-busy="true"
    >
      <span></span><span></span><span></span>
    </div>

    <p v-else-if="!loadFailed && nodes.length === 0" class="rollback-empty" data-checkpoint-empty>
      暂无节点。发送下一条指令前会自动保存。
    </p>

    <section
      v-if="confirmingCheckpoint"
      ref="restorePopoverElement"
      class="rollback-restore-popover"
      popover="manual"
      :style="restorePopoverStyle"
      aria-label="回到此节点"
    >
      <div class="rollback-restore-head">
        <div>
          <strong data-rollback-restore-title>回到此节点</strong>
          <span>{{ checkpointDescription(confirmingCheckpoint) }} · {{ dateLabel(confirmingCheckpoint.created_at) }}</span>
        </div>
      </div>
      <div class="rollback-scope-list" role="group" :aria-label="`选择回到 ${nodeAriaLabel(confirmingCheckpoint)} 时要恢复的内容`">
        <button
          type="button"
          class="scope-action"
          :data-confirm-rollback-conversation="confirmingCheckpoint.id"
          :disabled="busy || activeTurn"
          @click="restoreCheckpoint(confirmingCheckpoint, 'conversation')"
        >
          <strong>{{ busyAction === `${confirmingCheckpoint.id}:conversation` ? '恢复中…' : '仅恢复对话' }}</strong>
          <span>文件保持不变</span>
        </button>
        <button
          type="button"
          class="scope-action"
          :data-confirm-rollback-workspace="confirmingCheckpoint.id"
          :disabled="busy"
          @click="restoreCheckpoint(confirmingCheckpoint, 'workspace')"
        >
          <strong>{{ busyAction === `${confirmingCheckpoint.id}:workspace` ? '恢复中…' : '仅恢复文件' }}</strong>
          <span>对话保持不变</span>
        </button>
        <button
          type="button"
          class="scope-action"
          :data-confirm-rollback-all="confirmingCheckpoint.id"
          :disabled="busy || activeTurn"
          @click="restoreCheckpoint(confirmingCheckpoint, 'all')"
        >
          <strong>{{ busyAction === `${confirmingCheckpoint.id}:all` ? '恢复中…' : '全部恢复' }}</strong>
          <span>对话与文件</span>
        </button>
      </div>
      <button
        v-if="confirmingCheckpoint.actor_kind !== 'sub_agent' && belongsToCurrentFamily(confirmingCheckpoint)"
        type="button"
        class="fork-action"
        :data-fork-checkpoint="confirmingCheckpoint.id"
        :disabled="busy || activeTurn"
        @click="forkCheckpoint(confirmingCheckpoint)"
      >从此节点另开会话</button>
    </section>

    <div
      v-if="!loading && !loadFailed && nodes.length > 0"
      ref="graphElement"
      class="rollback-graph"
      data-checkpoint-graph
      :style="{ '--graph-gutter': `${graphLayout.gutter}px` }"
    >
      <svg
        class="rollback-graph-lines"
        :width="graphLayout.gutter"
        :height="graphLayout.height"
        :viewBox="`0 0 ${graphLayout.gutter} ${graphLayout.height}`"
        aria-hidden="true"
      >
        <path
          v-for="edge in graphLayout.edges"
          :key="`${edge.parentId}:${edge.nodeId}`"
          :class="['rollback-edge', `rollback-edge--${edge.kind}`]"
          :d="edge.path"
        />
      </svg>

      <ul class="rollback-list" role="tree" aria-label="存档节点图">
        <li
          v-for="(item, index) in graphLayout.nodes"
          :key="item.node.id"
          :class="['rollback-row', { 'rollback-row--selected': confirmingCheckpointId === item.node.id }]"
          data-checkpoint-row
          role="treeitem"
          :aria-label="nodeAriaLabel(item.node)"
          :aria-selected="confirmingCheckpointId === item.node.id"
        >
          <span
            class="rollback-node-dot"
            :class="`rollback-node-dot--${item.node.edge_kind}`"
            :style="{ left: `${item.x}px` }"
            aria-hidden="true"
          ></span>

          <button
            type="button"
            class="rollback-node-button"
            :data-rollback="item.node.id"
            :data-checkpoint-turn="item.node.turn_id"
            :disabled="busy || !belongsToCurrentFamily(item.node)"
            :title="checkpointDescription(item.node)"
            :aria-label="`回到 ${nodeAriaLabel(item.node)}`"
            @click="selectCheckpoint(item.node, $event)"
          >
            <span class="rollback-node-default">
              <strong>节点 {{ index + 1 }}</strong>
              <span v-if="branchLabel(item.node)" class="rollback-node-branch">{{ branchLabel(item.node) }}</span>
              <span v-else-if="heads[item.node.session_id] === item.node.id" class="rollback-node-current">当前</span>
              <span class="rollback-node-time">{{ dateLabel(item.node.created_at) }}</span>
            </span>
            <span class="rollback-node-hover" data-node-description>{{ checkpointDescription(item.node) }}</span>
          </button>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

export interface CoreSessionCheckpoint {
  id: string
  graph_id: string
  root_session_id: string
  session_id: string
  parent_checkpoint_id: string
  edge_kind: string
  turn_id: string
  actor_kind: string
  reason: string
  label: string
  work_root: string
  manifest_hash: string
  status: string
  created_at: string
}

export interface CoreSessionRollbackResult {
  operation_id: string
  checkpoint_id: string
  derived_checkpoint_id: string
  scope: RestoreScope
  status: string
  restored_paths: string[]
}

type RestoreScope = 'conversation' | 'workspace' | 'all'

export type CoreSessionOperationRequest = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

const props = withDefaults(defineProps<{
  sessionId: string
  request: CoreSessionOperationRequest
  activeTurn?: boolean
  turnPrompts?: Record<string, string>
}>(), { activeTurn: false, turnPrompts: () => ({}) })

const emit = defineEmits<{
  restored: [result: CoreSessionRollbackResult]
  'graph-loaded': [nodes: CoreSessionCheckpoint[]]
}>()

const nodes = ref<CoreSessionCheckpoint[]>([])
const heads = ref<Record<string, string>>({})
const loading = ref(false)
const loadFailed = ref(false)
const busy = ref(false)
const busyAction = ref('')
const error = ref('')
const notice = ref('')
const confirmingCheckpointId = ref('')
const graphElement = ref<HTMLElement | null>(null)
const restorePopoverElement = ref<HTMLElement | null>(null)
const restorePopoverStyle = ref<Record<string, string>>({ left: '12px', top: '12px' })
let loadSequence = 0

const graphLayout = computed(() => {
  const laneById = new Map<string, number>()
  const pointById = new Map<string, { x: number; y: number }>()
  let nextLane = 0
  const layoutNodes = nodes.value.map((node, index) => {
    const parentLane = laneById.get(node.parent_checkpoint_id)
    const parent = nodes.value.find(item => item.id === node.parent_checkpoint_id)
    const continuesLine = parentLane !== undefined
      && parent?.session_id === node.session_id
      && !['rollback', 'session_fork'].includes(node.edge_kind)
    const lane = continuesLine ? parentLane : (parentLane === undefined && index === 0 ? 0 : ++nextLane)
    laneById.set(node.id, lane)
    const x = 10 + Math.min(lane, 5) * 14
    const y = index * 48 + 24
    pointById.set(node.id, { x, y })
    return { node, x, y }
  })
  const gutter = Math.min(94, 34 + nextLane * 14)
  const edges = layoutNodes.flatMap(({ node }) => {
    const parent = pointById.get(node.parent_checkpoint_id)
    const child = pointById.get(node.id)
    if (!parent || !child) return []
    const middleY = parent.y + Math.max(10, (child.y - parent.y) / 2)
    return [{
      parentId: node.parent_checkpoint_id,
      nodeId: node.id,
      kind: node.edge_kind,
      path: `M ${parent.x} ${parent.y} V ${middleY} H ${child.x} V ${child.y}`,
    }]
  })
  return {
    nodes: layoutNodes,
    edges,
    gutter,
    height: Math.max(48, nodes.value.length * 48),
  }
})

const confirmingCheckpoint = computed(() => (
  nodes.value.find(node => node.id === confirmingCheckpointId.value) || null
))

watch(() => props.sessionId, () => {
  nodes.value = []
  heads.value = {}
  confirmingCheckpointId.value = ''
  notice.value = ''
  void loadGraph()
}, { immediate: true })

async function loadGraph() {
  const sessionId = props.sessionId.trim()
  const sequence = ++loadSequence
  error.value = ''
  loadFailed.value = false
  if (!sessionId) {
    nodes.value = []
    return
  }
  loading.value = true
  try {
    const result = await props.request('session.checkpoints.graph', { session_id: sessionId })
    if (sequence !== loadSequence) return
    nodes.value = Array.isArray(result.nodes) ? result.nodes.filter(isCheckpoint) : []
    heads.value = isRecord(result.heads) ? Object.fromEntries(
      Object.entries(result.heads).map(([key, value]) => [key, String(value)]),
    ) : {}
    emit('graph-loaded', [...nodes.value])
  } catch (cause) {
    if (sequence !== loadSequence) return
    nodes.value = []
    emit('graph-loaded', [])
    loadFailed.value = true
    error.value = errorMessage(cause)
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

function selectCheckpoint(checkpoint: CoreSessionCheckpoint, event?: Event) {
  if (busy.value || !belongsToCurrentFamily(checkpoint)) return
  confirmingCheckpointId.value = checkpoint.id
  const eventTarget = event?.currentTarget
  const anchor = typeof HTMLElement !== 'undefined' && eventTarget instanceof HTMLElement
    ? eventTarget
    : null
  void nextTick(() => {
    scheduleRestorePopover(anchor || findCheckpointButton(checkpoint.id))
  })
}

function selectTurn(turnId: string): boolean {
  const normalized = String(turnId || '').trim()
  if (!normalized) return false
  const checkpoint = [...nodes.value].reverse().find(node => node.turn_id === normalized)
  if (!checkpoint) return false
  selectCheckpoint(checkpoint)
  void nextTick(() => {
    const target = Array.from(
      graphElement.value?.querySelectorAll<HTMLElement>('[data-checkpoint-turn]') || [],
    ).find(element => element.dataset.checkpointTurn === normalized)
    if (target && typeof target.scrollIntoView === 'function') {
      target.scrollIntoView({ block: 'nearest' })
    }
    scheduleRestorePopover(target || null)
  })
  return true
}

function findCheckpointButton(checkpointId: string): HTMLElement | null {
  return Array.from(
    graphElement.value?.querySelectorAll<HTMLElement>('[data-rollback]') || [],
  ).find(element => element.dataset.rollback === checkpointId) || null
}

function scheduleRestorePopover(anchor: HTMLElement | null) {
  if (!anchor) return
  if (typeof requestAnimationFrame === 'function') {
    requestAnimationFrame(() => openRestorePopover(anchor))
    return
  }
  openRestorePopover(anchor)
}

function openRestorePopover(anchor: HTMLElement | null) {
  const popover = restorePopoverElement.value as (HTMLElement & { showPopover?: () => void }) | null
  if (!popover || !anchor) return
  try {
    if (typeof popover.showPopover === 'function' && !popover.matches(':popover-open')) {
      popover.showPopover()
    }
  } catch {
    // Test DOMs and older embedded webviews may not expose the Popover API.
  }
  const anchorRect = anchor.getBoundingClientRect()
  const popoverRect = popover.getBoundingClientRect()
  const viewportWidth = typeof window === 'undefined' ? 1280 : window.innerWidth
  const viewportHeight = typeof window === 'undefined' ? 800 : window.innerHeight
  const width = popoverRect.width || 244
  const height = popoverRect.height || 188
  const left = Math.max(12, Math.min(viewportWidth - width - 12, anchorRect.right - width))
  const top = anchorRect.bottom + height + 8 <= viewportHeight
    ? anchorRect.bottom + 6
    : Math.max(12, anchorRect.top - height - 6)
  restorePopoverStyle.value = { left: `${Math.round(left)}px`, top: `${Math.round(top)}px` }
}

function closeRestorePopover() {
  const popover = restorePopoverElement.value as (HTMLElement & { hidePopover?: () => void }) | null
  try {
    if (popover && typeof popover.hidePopover === 'function' && popover.matches(':popover-open')) {
      popover.hidePopover()
    }
  } catch {
    // The selected checkpoint can still be cleared when Popover is unavailable.
  }
  confirmingCheckpointId.value = ''
}

function handleOutsidePointerDown(event: PointerEvent) {
  if (!confirmingCheckpointId.value) return
  const target = event.target
  if (typeof Node === 'undefined' || !(target instanceof Node)) return
  if (restorePopoverElement.value?.contains(target)) return
  if (findCheckpointButton(confirmingCheckpointId.value)?.contains(target)) return
  closeRestorePopover()
}

function handleEscape(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !confirmingCheckpointId.value) return
  event.preventDefault()
  closeRestorePopover()
}

onMounted(() => {
  document.addEventListener('pointerdown', handleOutsidePointerDown, true)
  document.addEventListener('keydown', handleEscape)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleOutsidePointerDown, true)
  document.removeEventListener('keydown', handleEscape)
})

defineExpose({ loadGraph, selectTurn })

async function saveCheckpoint() {
  if (busy.value || props.activeTurn) return
  busy.value = true
  busyAction.value = 'save'
  error.value = ''
  try {
    const payload = await props.request('session.checkpoints.create', {
      session_id: props.sessionId,
      reason: 'manual_ui',
      label: '手动存档',
      actor_kind: 'tool',
    })
    const checkpoint = isRecord(payload.checkpoint) ? payload.checkpoint : {}
    notice.value = checkpoint.id ? '已保存当前状态' : '已保存'
    await loadGraph()
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
    busyAction.value = ''
  }
}

async function restoreCheckpoint(checkpoint: CoreSessionCheckpoint, scope: RestoreScope) {
  if (busy.value || (props.activeTurn && scope !== 'workspace')) return
  busy.value = true
  busyAction.value = `${checkpoint.id}:${scope}`
  error.value = ''
  notice.value = ''
  try {
    const payload = await props.request('session.checkpoints.restore', {
      session_id: props.sessionId,
      checkpoint_id: checkpoint.id,
      scope,
    })
    const result = normalizeRestoreResult(payload)
    confirmingCheckpointId.value = ''
    notice.value = restoreNotice(result)
    emit('restored', result)
    await loadGraph()
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
    busyAction.value = ''
  }
}

async function forkCheckpoint(checkpoint: CoreSessionCheckpoint) {
  if (busy.value || props.activeTurn) return
  busy.value = true
  busyAction.value = `fork:${checkpoint.id}`
  error.value = ''
  try {
    const payload = await props.request('session.fork', {
      session_id: props.sessionId,
      checkpoint_id: checkpoint.id,
    })
    notice.value = payload.session_id ? '已从这个时间点新建会话' : '已新建会话'
    await loadGraph()
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
    busyAction.value = ''
  }
}

function isCheckpoint(value: unknown): value is CoreSessionCheckpoint {
  if (!isRecord(value)) return false
  return typeof value.id === 'string' && typeof value.created_at === 'string'
}

function belongsToCurrentFamily(checkpoint: CoreSessionCheckpoint): boolean {
  const currentRoot = props.sessionId.split(':sub:', 1)[0]
  return checkpoint.root_session_id === currentRoot
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object'
}

function normalizeRestoreResult(value: Record<string, unknown>): CoreSessionRollbackResult {
  const operationId = String(value.operation_id || '')
  if (!operationId) throw new Error('读档操作未返回 operation_id')
  return {
    operation_id: operationId,
    checkpoint_id: String(value.checkpoint_id || ''),
    derived_checkpoint_id: String(value.derived_checkpoint_id || ''),
    scope: normalizeRestoreScope(value.scope),
    status: String(value.status || ''),
    restored_paths: Array.isArray(value.restored_paths) ? value.restored_paths.map(String) : [],
  }
}

function normalizeRestoreScope(value: unknown): RestoreScope {
  if (value === 'conversation' || value === 'workspace' || value === 'all') return value
  return 'all'
}

function restoreNotice(result: CoreSessionRollbackResult): string {
  if (result.scope === 'conversation') return '已回到该节点的对话，文件未改变'
  if (result.scope === 'workspace') {
    return result.restored_paths.length > 0
      ? `已恢复该节点的 ${result.restored_paths.length} 个文件，对话未改变`
      : '文件已经是这个时间点的状态'
  }
  return result.restored_paths.length > 0
    ? `已回到该节点，并恢复 ${result.restored_paths.length} 个文件`
    : '已回到该节点的对话和文件状态'
}

function checkpointDescription(checkpoint: CoreSessionCheckpoint): string {
  const prompt = String(props.turnPrompts[checkpoint.turn_id] || '').replace(/\s+/g, ' ').trim()
  if (prompt) return prompt
  const label = String(checkpoint.label || '').replace(/\s+/g, ' ').trim()
  if (label && label !== '用户指令前自动存档') return label
  return reasonLabel(checkpoint)
}

function actorLabel(actorKind: string): string {
  if (actorKind === 'sub_agent') return '子 Agent'
  if (actorKind === 'hook') return 'Hook'
  if (actorKind === 'fork') return '新会话'
  if (actorKind === 'restore') return '恢复'
  if (actorKind === 'tool') return '手动'
  return '主 Agent'
}

function branchLabel(checkpoint: CoreSessionCheckpoint): string {
  if (checkpoint.edge_kind === 'rollback') return '恢复后继续'
  if (checkpoint.edge_kind === 'session_fork') return '新会话'
  return ''
}

function reasonLabel(checkpoint: CoreSessionCheckpoint): string {
  if (checkpoint.reason === 'before_user_prompt') return '用户指令前自动存档'
  if (checkpoint.reason === 'before_rollback') return '读档前保护点'
  if (checkpoint.reason === 'rollback_conversation') return '仅恢复对话'
  if (checkpoint.reason === 'rollback_workspace') return '仅恢复文件'
  if (checkpoint.reason === 'rollback_all' || checkpoint.reason === 'rollback') return '全部恢复'
  if (checkpoint.reason === 'session_fork') return '分叉到新会话'
  return checkpoint.reason || '存档节点'
}

function nodeAriaLabel(checkpoint: CoreSessionCheckpoint): string {
  return `${checkpointDescription(checkpoint)}，${actorLabel(checkpoint.actor_kind)}，${dateLabel(checkpoint.created_at)}`
}

function dateLabel(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause)
}
</script>

<style scoped>
.core-session-rollback { display: grid; gap: 8px; color: var(--theme-backdrop-text, currentColor); }
.rollback-header, .rollback-title-row, .rollback-header-actions, .rollback-result,
.rollback-error, .rollback-restore-head, .rollback-node-default {
  display: flex;
  align-items: center;
}
.rollback-header { justify-content: space-between; gap: 10px; }
.rollback-title-row { min-width: 0; gap: 7px; }
.rollback-header h3 { margin: 0; font-size: 13px; font-weight: 700; line-height: 1.4; }
.rollback-node-branch, .rollback-node-current {
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 7%, transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 72%, transparent);
}
.rollback-count { color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 56%, transparent); font-size: 10px; }
.rollback-header-actions { flex: 0 0 auto; gap: 4px; }
.rollback-notice, .rollback-empty, .rollback-result, .rollback-error {
  margin: 0;
  border-radius: 8px;
  padding: 7px 8px;
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 5%, transparent);
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 74%, transparent);
  font-size: 11px;
  line-height: 1.45;
}
.rollback-notice { color: color-mix(in srgb, var(--orange, #d89a38) 84%, var(--theme-backdrop-text, currentColor) 16%); }
.rollback-result, .rollback-error { justify-content: space-between; gap: 8px; }
.rollback-result { color: color-mix(in srgb, var(--green, #4fa777) 82%, var(--theme-backdrop-text, currentColor) 18%); }
.rollback-error { color: color-mix(in srgb, var(--red, #df6b6b) 88%, var(--theme-backdrop-text, currentColor) 12%); }
.rollback-restore-popover {
  position: fixed;
  inset: auto;
  width: min(244px, calc(100vw - 24px));
  margin: 0;
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text, currentColor) 14%, transparent);
  border-radius: var(--radius);
  padding: 6px;
  background: var(--theme-backdrop-background, #171717);
  box-shadow: var(--shadow-md);
  color: var(--theme-backdrop-text, currentColor);
  overflow: hidden;
}
.rollback-restore-popover::backdrop {
  background: transparent;
}
.rollback-restore-head { padding: 5px 7px 7px; }
.rollback-restore-head > div { display: grid; min-width: 0; gap: 2px; }
.rollback-restore-head strong { font-size: 12px; font-weight: 680; }
.rollback-restore-head span { overflow: hidden; color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 54%, transparent); font-size: 10px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.rollback-scope-list { display: grid; gap: 1px; }
.scope-action {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  min-height: 36px;
  border: 0;
  border-radius: 6px;
  padding: 6px 8px;
  background: transparent;
  color: var(--theme-backdrop-text, currentColor);
  text-align: left;
}
.scope-action strong { overflow: hidden; font-size: 12px; font-weight: 620; text-overflow: ellipsis; white-space: nowrap; }
.scope-action span { overflow: hidden; color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 50%, transparent); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.scope-action:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) var(--alpha-hover), transparent); }
.fork-action {
  width: calc(100% - 4px);
  min-height: 34px;
  margin: 4px 2px 0;
  border: 0;
  border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text, currentColor) 9%, transparent);
  padding: 7px 6px 3px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 62%, transparent);
  font-size: 11px;
  text-align: left;
}
.fork-action:hover:not(:disabled) { color: var(--theme-backdrop-text, currentColor); }
.rollback-graph { position: relative; max-height: 360px; overflow: auto; --graph-gutter: 48px; }
.rollback-graph-lines { position: absolute; inset: 0 auto auto 0; pointer-events: none; overflow: visible; }
.rollback-edge { fill: none; stroke: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 24%, transparent); stroke-width: 1.25; }
.rollback-edge--rollback { stroke: color-mix(in srgb, var(--orange, #d89a38) 68%, transparent); }
.rollback-edge--session_fork { stroke: color-mix(in srgb, var(--blue, #6c8ed4) 72%, transparent); }
.rollback-edge--hook { stroke-dasharray: 3 3; }
.rollback-list { display: grid; margin: 0; padding: 0; list-style: none; }
.rollback-row {
  position: relative;
  min-width: 0;
  min-height: 48px;
  padding-left: var(--graph-gutter);
  border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text, currentColor) 7%, transparent);
}
.rollback-row:first-child { border-top: 0; }
.rollback-row--selected { background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) var(--alpha-hover), transparent); }
.rollback-row--selected .rollback-node-dot { box-shadow: 0 0 0 3px color-mix(in srgb, var(--theme-backdrop-text, currentColor) var(--alpha-active), transparent); }
.rollback-node-dot {
  position: absolute;
  top: 18px;
  z-index: 1;
  width: 12px;
  height: 12px;
  transform: translateX(-50%);
  border: 2px solid var(--theme-backdrop-background, #171717);
  border-radius: 50%;
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 72%, transparent);
}
.rollback-node-dot--rollback { background: var(--orange, #d89a38); }
.rollback-node-dot--session_fork { background: var(--blue, #6c8ed4); }
.rollback-node-dot--hook { background: var(--green, #4fa777); }
.rollback-node-button {
  position: relative;
  width: 100%;
  height: 48px;
  overflow: hidden;
  border: 0;
  border-radius: 6px;
  padding: 0 7px;
  background: transparent;
  color: var(--theme-backdrop-text, currentColor);
  text-align: left;
}
.rollback-node-default { min-width: 0; gap: 5px; transition: opacity 160ms ease-out; }
.rollback-node-default strong { flex: 0 0 auto; font-size: 12px; font-weight: 650; }
.rollback-node-branch, .rollback-node-current { flex: 0 0 auto; padding: 1px 5px; font-size: 9px; }
.rollback-node-time { margin-left: auto; color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 62%, transparent); font-size: 10px; }
.rollback-node-hover {
  position: absolute;
  inset: 0 7px;
  display: flex;
  align-items: center;
  overflow: hidden;
  background: var(--theme-backdrop-background, #171717);
  color: var(--theme-backdrop-text, currentColor);
  font-size: 11px;
  line-height: 1.35;
  opacity: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: opacity 160ms ease-out;
}
.rollback-node-button:hover:not(:disabled) .rollback-node-hover,
.rollback-node-button:focus-visible .rollback-node-hover { opacity: 1; }
.rollback-node-button:hover:not(:disabled) .rollback-node-default,
.rollback-node-button:focus-visible .rollback-node-default { opacity: 0; }
.quiet-action, .icon-action {
  flex: 0 0 auto;
  min-height: 26px;
  border-radius: 6px;
  font-size: 11px;
  transition: background-color 160ms ease-out, border-color 160ms ease-out, color 160ms ease-out;
}
.quiet-action { border: 1px solid color-mix(in srgb, var(--theme-backdrop-text, currentColor) 15%, transparent); padding: 0 7px; background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 84%, transparent); }
.icon-action { width: 26px; border: 0; padding: 0; background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 72%, transparent); font-size: 15px; }
.quiet-action:hover:not(:disabled), .icon-action:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) var(--alpha-hover), transparent); color: var(--theme-backdrop-text, currentColor); }
.quiet-action:focus-visible, .icon-action:focus-visible, .scope-action:focus-visible,
.fork-action:focus-visible, .rollback-node-button:focus-visible { outline: 2px solid var(--blue, #6c8ed4); outline-offset: 2px; }
.quiet-action:disabled, .icon-action:disabled, .scope-action:disabled,
.fork-action:disabled, .rollback-node-button:disabled { cursor: default; opacity: .42; }
.rollback-loading { display: grid; gap: 7px; padding: 5px 0; }
.rollback-loading span { height: 9px; border-radius: 4px; background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 7%, transparent); }
.rollback-loading span:nth-child(2) { width: 82%; }
.rollback-loading span:nth-child(3) { width: 68%; }
@media (prefers-reduced-motion: reduce) {
  .quiet-action, .icon-action, .scope-action, .rollback-node-default, .rollback-node-hover { transition: none; }
}
</style>
