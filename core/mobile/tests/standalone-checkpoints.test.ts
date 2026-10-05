import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CoreAppSnapshot } from '@lamtools/ui'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import {
  createCheckpointRpc,
  forkSnapshotUpToTurn,
  truncateSnapshotAfterTurn,
  turnOwnedItems,
} from '../src/standalone/StandaloneCheckpoints'

/** A session with three turns, the shape the transport builds. */
function snapshot(): CoreAppSnapshot {
  return {
    thread_id: 's1',
    revision: 3,
    snapshot_seq: 3,
    core: {
      thread_id: 's1',
      revision: 3,
      snapshot_seq: 3,
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['turn-1:user', 'turn-1:assistant'], seq: 1 },
        'turn-2': { turn_id: 'turn-2', status: 'completed', items: ['turn-2:user', 'turn-2:assistant'], seq: 2 },
        'turn-3': { turn_id: 'turn-3', status: 'running', items: ['turn-3:user', 'turn-3:assistant'], seq: 3 },
      },
      items: {
        'turn-1:user': { id: 'turn-1:user', payload: {}, status: 'completed' },
        'turn-1:assistant': { id: 'turn-1:assistant', payload: {}, status: 'completed' },
        'turn-2:user': { id: 'turn-2:user', payload: {}, status: 'completed' },
        'turn-2:assistant': { id: 'turn-2:assistant', payload: {}, status: 'completed' },
        'turn-3:user': { id: 'turn-3:user', payload: {}, status: 'completed' },
        'turn-3:assistant': { id: 'turn-3:assistant', payload: {}, status: 'running' },
      },
    },
  } as unknown as CoreAppSnapshot
}

const nodes = [
  { id: 'ckpt-1', session_id: 's1', turn_id: 'turn-1', graph_id: 'g', status: 'ready', created_at: 'a' },
  { id: 'ckpt-2', session_id: 's1', turn_id: 'turn-2', graph_id: 'g', status: 'ready', created_at: 'b' },
  { id: 'ckpt-3', session_id: 's1', turn_id: 'turn-3', graph_id: 'g', status: 'ready', created_at: 'c' },
].map(node => ({
  ...node,
  root_session_id: 's1', parent_checkpoint_id: '', edge_kind: 'turn', actor_kind: 'agent',
  reason: '', label: '', work_root: '', manifest_hash: '',
}))

afterEach(() => { invokeMock.mockReset(); vi.unstubAllGlobals() })

describe('session checkpoints', () => {
  it('rolls a conversation back to a turn and forgets what came after', () => {
    const target = snapshot()
    expect(turnOwnedItems(target, 'turn-2')).toEqual(['turn-2:user', 'turn-2:assistant'])
    const removed = truncateSnapshotAfterTurn(target, 'turn-2')
    expect(removed).toEqual({ removed_items: 2, removed_turns: 1 })
    expect(Object.keys(target.core!.turns!)).toEqual(['turn-1', 'turn-2'])
    expect(Object.keys(target.core!.items!)).toEqual([
      'turn-1:user', 'turn-1:assistant', 'turn-2:user', 'turn-2:assistant',
    ])
    // An unknown turn changes nothing rather than wiping the session.
    expect(truncateSnapshotAfterTurn(target, 'turn-nowhere'))
      .toEqual({ removed_items: 0, removed_turns: 0 })
    expect(Object.keys(target.core!.turns!).length).toBe(2)
  })

  it('keeps exactly the branch a fork needs', () => {
    const part = forkSnapshotUpToTurn(snapshot(), 'turn-2')
    expect(Object.keys(part.turns)).toEqual(['turn-1', 'turn-2'])
    expect(Object.keys(part.items)).toEqual([
      'turn-1:user', 'turn-1:assistant', 'turn-2:user', 'turn-2:assistant',
    ])
  })

  it('answers graph, restore, fork and rollback as conversation-only payloads', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    const forks: Array<{ sessionId: string; turnId: string; title: string }> = []
    const truncations: Array<{ sessionId: string; turnId: string }> = []
    const rpc = createCheckpointRpc({
      sessionProjectId: async () => 'p1',
      forkSession: async (sessionId, turnId, title) => {
        forks.push({ sessionId, turnId, title })
        return { id: 's2', title }
      },
      truncateSession: async (sessionId, turnId) => {
        truncations.push({ sessionId, turnId })
        return { removed_items: 2, removed_turns: 1 }
      },
      checkpointTurn: async checkpointId => nodes.find(node => node.id === checkpointId)?.turn_id || '',
    })
    invokeMock.mockImplementation(async (command: string, args: Record<string, unknown> = {}) => {
      if (command === 'sunday_checkpoint_graph') {
        return { nodes, heads: { s1: 'ckpt-3' } }
      }
      if (command === 'sunday_checkpoint_get') {
        return { checkpoint: nodes.find(node => node.id === args.checkpointId) }
      }
      throw new Error(`unexpected ${command}`)
    })

    const graph = await rpc('session.checkpoints.graph', { session_id: 's1' })
    expect((graph?.nodes as unknown[]).length).toBe(3)
    expect(graph?.heads).toEqual({ s1: 'ckpt-3' })
    const list = await rpc('session.checkpoints.list', { session_id: 's1' })
    expect((list?.nodes as unknown[]).length).toBe(3)
    expect(list?.heads).toBeUndefined()

    // 恢复只作用于对话：截断到该检查点的回合，并如实说明工作区没有动。
    expect(await rpc('session.checkpoints.restore', { session_id: 's1', checkpoint_id: 'ckpt-2' }))
      .toMatchObject({
        mode: 'conversation_only',
        turn_id: 'turn-2',
        restored_paths: [],
        restored: { conversation: true, runtime: true, workspace: false },
        removed_items: 2,
      })
    expect(truncations).toEqual([{ sessionId: 's1', turnId: 'turn-2' }])

    const forked = await rpc('session.fork', { session_id: 's1', checkpoint_id: 'ckpt-2', title: '分支' })
    expect(forks).toEqual([{ sessionId: 's1', turnId: 'turn-2', title: '分支' }])
    expect(forked).toEqual({ session: { id: 's2', title: '分支' }, checkpoint_id: 'ckpt-2' })

    // 撤回给回合就直接截断；没给回合就退到最近一个检查点（撤销最后一轮）。
    // 两条路径都只删对话，文件与成果不动。
    const rolledBack = await rpc('session.rollback', { session_id: 's1', turn_id: 'turn-2' })
    expect(rolledBack).toMatchObject({
      mode: 'conversation_only',
      turn_id: 'turn-2',
      removed_items: 2,
      restored: { conversation: true, runtime: true, workspace: false, external_effects: false },
    })
    const lastTurn = await rpc('session.rollback', { session_id: 's1' })
    expect(lastTurn).toMatchObject({ mode: 'conversation_only', turn_id: 'turn-3' })
    expect(truncations).toEqual([
      { sessionId: 's1', turnId: 'turn-2' },
      { sessionId: 's1', turnId: 'turn-2' },
      { sessionId: 's1', turnId: 'turn-3' },
    ])

    await expect(rpc('session.checkpoints.graph', {})).rejects.toThrow('session_id is required')
    await expect(rpc('session.fork', { session_id: 's1' })).rejects.toThrow('checkpoint_id 必填')
    expect(await rpc('artifact.list', {})).toBeNull()
  })
})
