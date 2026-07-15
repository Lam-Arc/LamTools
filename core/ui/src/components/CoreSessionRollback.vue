<template>
  <section class="core-session-rollback" aria-labelledby="core-session-rollback-title">
    <header class="rollback-header">
      <div>
        <h3 id="core-session-rollback-title">回滚点</h3>
        <p>同时恢复对话与工作区文件</p>
      </div>
      <button
        type="button"
        class="quiet-action"
        :disabled="loading || busy"
        aria-label="刷新回滚点"
        @click="loadCheckpoints"
      >刷新</button>
    </header>

    <p v-if="activeTurn" class="rollback-notice" data-active-turn-notice>
      当前任务正在运行，请在任务结束或停止后回滚。
    </p>

    <div
      v-if="notice"
      class="rollback-result"
      role="status"
      aria-live="polite"
    >
      <span>{{ notice }}</span>
      <button
        v-if="undoOperationId"
        type="button"
        class="quiet-action"
        data-undo-rollback
        :disabled="busy || activeTurn"
        @click="undoRollback"
      >{{ busyAction === 'undo' ? '正在撤销…' : '撤销回滚' }}</button>
    </div>

    <div v-if="error" class="rollback-error" role="alert">
      <span>{{ error }}</span>
      <button
        v-if="loadFailed"
        type="button"
        class="quiet-action"
        data-retry-checkpoints
        :disabled="loading"
        @click="loadCheckpoints"
      >重试</button>
    </div>

    <div
      v-if="loading && checkpoints.length === 0"
      class="rollback-loading"
      aria-label="正在加载回滚点"
      aria-busy="true"
    >
      <span></span><span></span><span></span>
    </div>

    <p
      v-else-if="!loadFailed && checkpoints.length === 0"
      class="rollback-empty"
      data-checkpoint-empty
    >还没有可回滚的检查点。开始下一轮任务时会自动创建。</p>

    <ul v-else class="rollback-list" aria-label="可用回滚点">
      <li
        v-for="checkpoint in checkpoints"
        :key="checkpoint.id"
        class="rollback-row"
        data-checkpoint-row
      >
        <div class="rollback-copy">
          <strong>{{ actorLabel(checkpoint.actor_kind) }} · {{ dateLabel(checkpoint.created_at) }}</strong>
          <span :title="checkpoint.turn_id">{{ checkpoint.turn_id || checkpoint.id }}</span>
        </div>

        <div v-if="confirmingCheckpointId === checkpoint.id" class="rollback-confirm">
          <button
            type="button"
            class="quiet-action"
            :disabled="busy"
            @click="confirmingCheckpointId = ''"
          >取消</button>
          <button
            type="button"
            class="danger-action"
            :data-confirm-rollback="checkpoint.id"
            :disabled="busy || activeTurn"
            @click="rollback(checkpoint)"
          >{{ busyAction === checkpoint.id ? '正在回滚…' : '确认回滚' }}</button>
        </div>
        <button
          v-else
          type="button"
          class="quiet-action"
          :data-rollback="checkpoint.id"
          :disabled="busy || activeTurn"
          :aria-label="`回滚到 ${actorLabel(checkpoint.actor_kind)} ${dateLabel(checkpoint.created_at)} 的检查点`"
          @click="confirmingCheckpointId = checkpoint.id"
        >回滚</button>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

export interface CoreSessionCheckpoint {
  id: string
  session_id: string
  turn_id: string
  actor_kind: string
  work_root: string
  manifest_hash: string
  status: string
  created_at: string
}

export interface CoreSessionRollbackResult {
  operation_id: string
  checkpoint_id: string
  undo_checkpoint_id: string
  status: string
  restored_paths: string[]
}

export type CoreSessionOperationRequest = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

const props = withDefaults(defineProps<{
  sessionId: string
  request: CoreSessionOperationRequest
  activeTurn?: boolean
}>(), {
  activeTurn: false,
})

const emit = defineEmits<{
  restored: [result: CoreSessionRollbackResult]
  undone: [result: CoreSessionRollbackResult]
}>()

const checkpoints = ref<CoreSessionCheckpoint[]>([])
const loading = ref(false)
const loadFailed = ref(false)
const busy = ref(false)
const busyAction = ref('')
const error = ref('')
const notice = ref('')
const confirmingCheckpointId = ref('')
const undoOperationId = ref('')
let loadSequence = 0

watch(() => props.sessionId, () => {
  checkpoints.value = []
  confirmingCheckpointId.value = ''
  undoOperationId.value = ''
  notice.value = ''
  void loadCheckpoints()
}, { immediate: true })

async function loadCheckpoints() {
  const sessionId = props.sessionId.trim()
  const sequence = ++loadSequence
  error.value = ''
  loadFailed.value = false
  if (!sessionId) {
    checkpoints.value = []
    return
  }
  loading.value = true
  try {
    const result = await props.request('session.checkpoints.list', { session_id: sessionId })
    if (sequence !== loadSequence) return
    checkpoints.value = Array.isArray(result.checkpoints)
      ? result.checkpoints.filter(isCheckpoint)
      : []
  } catch (cause) {
    if (sequence !== loadSequence) return
    checkpoints.value = []
    loadFailed.value = true
    error.value = errorMessage(cause)
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

async function rollback(checkpoint: CoreSessionCheckpoint) {
  if (busy.value || props.activeTurn) return
  busy.value = true
  busyAction.value = checkpoint.id
  error.value = ''
  notice.value = ''
  try {
    const payload = await props.request('session.rollback', {
      session_id: props.sessionId,
      checkpoint_id: checkpoint.id,
    })
    const result = normalizeRestoreResult(payload)
    undoOperationId.value = result.operation_id
    confirmingCheckpointId.value = ''
    notice.value = result.restored_paths.length > 0
      ? `已恢复对话与文件（${result.restored_paths.length} 项）`
      : '已恢复对话与文件'
    emit('restored', result)
    await loadCheckpoints()
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
    busyAction.value = ''
  }
}

async function undoRollback() {
  if (!undoOperationId.value || busy.value || props.activeTurn) return
  busy.value = true
  busyAction.value = 'undo'
  error.value = ''
  try {
    const payload = await props.request('session.rollback.undo', {
      session_id: props.sessionId,
      operation_id: undoOperationId.value,
    })
    const result = normalizeRestoreResult(payload)
    undoOperationId.value = ''
    notice.value = '已撤销回滚，对话与文件已恢复'
    emit('undone', result)
    await loadCheckpoints()
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
    busyAction.value = ''
  }
}

function isCheckpoint(value: unknown): value is CoreSessionCheckpoint {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return typeof item.id === 'string' && typeof item.created_at === 'string'
}

function normalizeRestoreResult(value: Record<string, unknown>): CoreSessionRollbackResult {
  const operationId = String(value.operation_id || '')
  if (!operationId) throw new Error('回滚操作未返回 operation_id')
  return {
    operation_id: operationId,
    checkpoint_id: String(value.checkpoint_id || ''),
    undo_checkpoint_id: String(value.undo_checkpoint_id || ''),
    status: String(value.status || ''),
    restored_paths: Array.isArray(value.restored_paths)
      ? value.restored_paths.map(String)
      : [],
  }
}

function actorLabel(actorKind: string): string {
  if (actorKind === 'sub_agent') return '子 Agent'
  if (actorKind === 'restore') return '回滚前'
  return '主 Agent'
}

function dateLabel(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause)
}
</script>

<style scoped>
.core-session-rollback {
  display: grid;
  gap: 10px;
  color: var(--theme-backdrop-text, currentColor);
}

.rollback-header,
.rollback-result,
.rollback-error,
.rollback-row,
.rollback-confirm {
  display: flex;
  align-items: center;
}

.rollback-header {
  justify-content: space-between;
  gap: 12px;
}

.rollback-header h3,
.rollback-header p,
.rollback-notice,
.rollback-empty {
  margin: 0;
}

.rollback-header h3 {
  font-size: 13px;
  font-weight: 700;
  line-height: 1.4;
}

.rollback-header p,
.rollback-notice,
.rollback-empty,
.rollback-error,
.rollback-result {
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 62%, transparent);
  font-size: 12px;
  line-height: 1.5;
}

.rollback-header p {
  margin-top: 2px;
}

.rollback-notice,
.rollback-empty,
.rollback-result,
.rollback-error {
  border-radius: 8px;
  padding: 8px 9px;
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 5%, transparent);
}

.rollback-notice {
  color: color-mix(in srgb, var(--orange, #d89a38) 76%, var(--theme-backdrop-text, currentColor) 24%);
}

.rollback-result,
.rollback-error {
  justify-content: space-between;
  gap: 10px;
}

.rollback-result {
  color: color-mix(in srgb, var(--green, #4fa777) 74%, var(--theme-backdrop-text, currentColor) 26%);
}

.rollback-error {
  color: color-mix(in srgb, var(--red, #df6b6b) 80%, var(--theme-backdrop-text, currentColor) 20%);
}

.rollback-list {
  max-height: 280px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.rollback-row {
  min-width: 0;
  min-height: 48px;
  justify-content: space-between;
  gap: 10px;
  border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text, currentColor) 8%, transparent);
}

.rollback-row:first-child {
  border-top: 0;
}

.rollback-copy {
  min-width: 0;
}

.rollback-copy strong,
.rollback-copy span {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rollback-copy strong {
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 82%, transparent);
  font-size: 12px;
  font-weight: 650;
}

.rollback-copy span {
  margin-top: 2px;
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 48%, transparent);
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 11px;
}

.quiet-action,
.danger-action {
  flex: 0 0 auto;
  min-height: 28px;
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text, currentColor) 13%, transparent);
  border-radius: 7px;
  padding: 0 9px;
  background: transparent;
  color: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 76%, transparent);
  font-size: 12px;
}

.quiet-action:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 7%, transparent);
  color: var(--theme-backdrop-text, currentColor);
}

.danger-action {
  border-color: color-mix(in srgb, var(--red, #df6b6b) 44%, transparent);
  background: color-mix(in srgb, var(--red, #df6b6b) 11%, transparent);
  color: color-mix(in srgb, var(--red, #df6b6b) 82%, white 12%);
}

.danger-action:hover:not(:disabled) {
  background: color-mix(in srgb, var(--red, #df6b6b) 17%, transparent);
}

.quiet-action:disabled,
.danger-action:disabled {
  cursor: default;
  opacity: .42;
}

.rollback-confirm {
  flex: 0 0 auto;
  gap: 5px;
}

.rollback-loading {
  display: grid;
  gap: 7px;
  padding: 5px 0;
}

.rollback-loading span {
  height: 10px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--theme-backdrop-text, currentColor) 7%, transparent);
}

.rollback-loading span:nth-child(2) { width: 82%; }
.rollback-loading span:nth-child(3) { width: 68%; }

@media (prefers-reduced-motion: reduce) {
  .quiet-action,
  .danger-action {
    transition: none;
  }
}
</style>
