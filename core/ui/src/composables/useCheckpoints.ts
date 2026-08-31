import { computed, ref } from 'vue'

export interface CoreCheckpointNode {
  id: string
  graph_id?: string
  root_session_id: string
  session_id: string
  parent_checkpoint_id: string
  edge_kind: string
  turn_id: string
  actor_kind: string
  reason: string
  label?: string
  work_root?: string
  manifest_hash?: string
  status?: string
  created_at: string
}

export type CoreCheckpointRestoreScope = 'conversation' | 'workspace' | 'all'
export type CoreCheckpointState = 'idle' | 'loading' | 'ready' | 'error'

export interface CoreCheckpointRestoreResult {
  operation_id: string
  checkpoint_id: string
  derived_checkpoint_id: string
  scope: CoreCheckpointRestoreScope
  status: string
  restored_paths: string[]
}

export type CoreCheckpointRequest = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

export function useCheckpoints(request: CoreCheckpointRequest) {
  const graph = ref<CoreCheckpointNode[]>([])
  const heads = ref<Record<string, string>>({})
  const loading = ref(false)
  const error = ref('')
  const loaded = ref(false)
  let loadSequence = 0

  const state = computed<CoreCheckpointState>(() => {
    if (loading.value) return 'loading'
    if (error.value) return 'error'
    return loaded.value ? 'ready' : 'idle'
  })

  const checkpointByTurnId = computed<Record<string, string>>(() => {
    const result: Record<string, string> = {}
    for (const node of graph.value) {
      if (
        node.actor_kind === 'main'
        && node.reason === 'before_user_prompt'
        && node.turn_id
      ) {
        result[node.turn_id] = node.id
      }
    }
    return result
  })

  const checkpointTurnIds = computed(() => new Set(Object.keys(checkpointByTurnId.value)))

  function reset() {
    loadSequence += 1
    graph.value = []
    heads.value = {}
    loading.value = false
    error.value = ''
    loaded.value = false
  }

  function beginLoading() {
    loading.value = true
    error.value = ''
  }

  function setGraph(nodes: CoreCheckpointNode[], nextHeads: Record<string, string> = {}) {
    graph.value = nodes.filter(isCheckpointNode)
    heads.value = { ...nextHeads }
    loading.value = false
    error.value = ''
    loaded.value = true
  }

  function setError(value: unknown) {
    loading.value = false
    error.value = errorMessage(value)
    loaded.value = false
  }

  async function load(sessionId: string): Promise<CoreCheckpointNode[]> {
    const normalized = sessionId.trim()
    const sequence = ++loadSequence
    beginLoading()
    if (!normalized) {
      if (sequence === loadSequence) reset()
      return []
    }
    try {
      const result = await request('session.checkpoints.graph', { session_id: normalized })
      if (sequence !== loadSequence) return []
      const nodes = Array.isArray(result.nodes) ? result.nodes.filter(isCheckpointNode) : []
      const nextHeads = isRecord(result.heads)
        ? Object.fromEntries(Object.entries(result.heads).map(([key, value]) => [key, String(value)]))
        : {}
      setGraph(nodes, nextHeads)
      return nodes
    } catch (cause) {
      if (sequence === loadSequence) {
        graph.value = []
        heads.value = {}
        setError(cause)
      }
      return []
    }
  }

  function getCheckpointForTurn(turnId: string): string {
    return checkpointByTurnId.value[String(turnId || '').trim()] || ''
  }

  async function restore(
    sessionId: string,
    checkpointId: string,
    scope: CoreCheckpointRestoreScope,
  ): Promise<Record<string, unknown>> {
    return request('session.checkpoints.restore', {
      session_id: sessionId,
      checkpoint_id: checkpointId,
      scope,
    })
  }

  async function fork(sessionId: string, checkpointId: string): Promise<Record<string, unknown>> {
    return request('session.fork', {
      session_id: sessionId,
      checkpoint_id: checkpointId,
    })
  }

  return {
    graph,
    heads,
    loading,
    error,
    state,
    checkpointByTurnId,
    checkpointTurnIds,
    reset,
    beginLoading,
    setGraph,
    setError,
    load,
    reload: load,
    getCheckpointForTurn,
    restore,
    fork,
  }
}

function isCheckpointNode(value: unknown): value is CoreCheckpointNode {
  return isRecord(value)
    && typeof value.id === 'string'
    && typeof value.root_session_id === 'string'
    && typeof value.session_id === 'string'
    && typeof value.parent_checkpoint_id === 'string'
    && typeof value.edge_kind === 'string'
    && typeof value.turn_id === 'string'
    && typeof value.actor_kind === 'string'
    && typeof value.reason === 'string'
    && typeof value.created_at === 'string'
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function errorMessage(value: unknown): string {
  return value instanceof Error ? value.message : String(value)
}
