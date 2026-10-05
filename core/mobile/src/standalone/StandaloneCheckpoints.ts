import type { CoreAppSnapshot } from '@lamtools/ui'
import {
  hasEmbeddedRustCore,
  readEmbeddedCheckpoint,
  readEmbeddedCheckpointGraph,
} from '../native/rustAgent'

/**
 * Session checkpoints for the standalone transport.
 *
 * 撤回与恢复都只作用于对话上下文：手机端截断本地会话快照，永不触碰文件与成果
 * （成果没有历史版本）。分叉同样只复制对话，因为只有这一侧持有会话存储。
 */
export interface CheckpointDeps {
  /** Session metadata, used to find the project a checkpoint belongs to. */
  sessionProjectId: (sessionId: string) => Promise<string>
  /** Copy a session up to (and including) a turn into a new one. */
  forkSession: (sessionId: string, turnId: string, title: string) => Promise<{ id: string; title: string }>
  /** Drop everything after a turn, so the conversation matches the files. */
  truncateSession: (sessionId: string, turnId: string) => Promise<{ removed_items: number; removed_turns: number }>
  /** The turn a checkpoint was taken at, for fork and rollback. */
  checkpointTurn: (checkpointId: string) => Promise<string>
}

export function createCheckpointRpc(deps: CheckpointDeps) {
  return async function checkpointRpc(
    method: string,
    params: Record<string, unknown>,
  ): Promise<Record<string, unknown> | null> {
    const sessionId = String(params.session_id || params.sessionId || '')
    const checkpointId = String(params.checkpoint_id || params.checkpointId || '')
    if (method === 'session.checkpoints.graph' || method === 'session.checkpoints.list') {
      if (!sessionId) throw new Error('session_id is required')
      if (!hasEmbeddedRustCore()) return { nodes: [], heads: {} }
      const graph = await readEmbeddedCheckpointGraph(sessionId)
      return method === 'session.checkpoints.list'
        ? { nodes: graph.nodes }
        : { nodes: graph.nodes, heads: graph.heads }
    }
    if (method === 'session.checkpoints.restore') {
      if (!sessionId || !checkpointId) throw new Error('session_id 与 checkpoint_id 必填')
      const turnId = await deps.checkpointTurn(checkpointId)
      if (!turnId) throw new Error('该检查点没有可回退的回合')
      const truncated = await deps.truncateSession(sessionId, turnId)
      return {
        session_id: sessionId,
        checkpoint_id: checkpointId,
        turn_id: turnId,
        mode: 'conversation_only',
        restored: { conversation: true, runtime: true, workspace: false, external_effects: false },
        restored_paths: [],
        ...truncated,
      }
    }
    if (method === 'session.fork') {
      if (!sessionId || !checkpointId) throw new Error('session_id 与 checkpoint_id 必填')
      const turnId = await deps.checkpointTurn(checkpointId)
      if (!turnId) throw new Error('该检查点没有可派生的回合')
      const title = String(params.title || '分支会话')
      const created = await deps.forkSession(sessionId, turnId, title)
      return { session: { id: created.id, title: created.title }, checkpoint_id: checkpointId }
    }
    if (method === 'session.rollback') {
      if (!sessionId) throw new Error('session_id 必填')
      const requested = String(params.turn_id || params.turnId || '')
      let turnId = requested
      if (!turnId) {
        // 没给回合时退回到最近一个检查点，也就是桌面的"撤销最后一轮"。
        const graph = hasEmbeddedRustCore()
          ? await readEmbeddedCheckpointGraph(sessionId)
          : { nodes: [], heads: {} }
        const target = graph.nodes.filter(node => node.session_id === sessionId).at(-1)
        if (!target) throw new Error('找不到对应的检查点')
        turnId = target.turn_id
      }
      const truncated = await deps.truncateSession(sessionId, turnId)
      return {
        session_id: sessionId,
        turn_id: turnId,
        mode: 'conversation_only',
        restored: { conversation: true, runtime: true, workspace: false, external_effects: false },
        restored_paths: [],
        ...truncated,
      }
    }
    return null
  }
}

/**
 * The items and turns that belong to a turn.
 *
 * Items are named `${turnId}:…` by the transport and carry the turn in their
 * payload, so an id prefix is the signal; older items are matched on
 * `turn_id` when it is present.
 */
export function turnOwnedItems(snapshot: CoreAppSnapshot, turnId: string): string[] {
  const turn = snapshot.core?.turns?.[turnId]
  if (turn) return [...(turn.items || [])]
  return Object.keys(snapshot.core?.items || {}).filter(id => id.startsWith(`${turnId}:`))
}

/**
 * Drop everything after a turn, in place.
 *
 * Returns how many items and turns went away, so the caller can report a
 * rollback that changed nothing instead of claiming success.
 */
export function truncateSnapshotAfterTurn(
  snapshot: CoreAppSnapshot,
  turnId: string,
): { removed_items: number; removed_turns: number } {
  const core = snapshot.core
  if (!core) return { removed_items: 0, removed_turns: 0 }
  const order = Object.values(core.turns || {}).sort((left, right) => Number(left.seq || 0) - Number(right.seq || 0))
  const index = order.findIndex(turn => turn.turn_id === turnId)
  if (index < 0) return { removed_items: 0, removed_turns: 0 }
  const kept = new Set(order.slice(0, index + 1).map(turn => turn.turn_id))
  let removed_items = 0
  for (const id of Object.keys(core.items || {})) {
    const owner = order.find(turn => (turn.items || []).includes(id))
    const ownerId = owner?.turn_id || id.split(':')[0]
    if (!kept.has(ownerId)) {
      delete core.items![id]
      removed_items += 1
    }
  }
  let removed_turns = 0
  for (const turn of order.slice(index + 1)) {
    delete core.turns![turn.turn_id]
    removed_turns += 1
  }
  return { removed_items, removed_turns }
}

/**
 * The part of a session that a fork keeps: every item and turn up to a turn,
 * re-keyed so the branch owns its own copies.
 */
export function forkSnapshotUpToTurn(
  snapshot: CoreAppSnapshot,
  turnId: string,
): { items: Record<string, unknown>; turns: Record<string, unknown> } {
  const core = snapshot.core
  if (!core) return { items: {}, turns: {} }
  const order = Object.values(core.turns || {}).sort((left, right) => Number(left.seq || 0) - Number(right.seq || 0))
  const index = order.findIndex(turn => turn.turn_id === turnId)
  const keptTurns = order.slice(0, index < 0 ? 0 : index + 1)
  const keptIds = new Set(keptTurns.flatMap(turn => turn.items || []))
  const items: Record<string, unknown> = {}
  for (const [id, item] of Object.entries(core.items || {})) {
    if (keptIds.has(id) || id.startsWith(`${turnId}:`)) items[id] = item
  }
  const turns: Record<string, unknown> = {}
  for (const turn of keptTurns) turns[turn.turn_id] = turn
  return { items, turns }
}
