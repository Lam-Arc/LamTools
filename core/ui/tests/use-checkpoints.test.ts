import { describe, expect, it, vi } from 'vitest'
import { useCheckpoints } from '../src/composables/useCheckpoints'

const node = {
  id: 'checkpoint-1',
  root_session_id: 'session-1',
  session_id: 'session-1',
  parent_checkpoint_id: '',
  edge_kind: 'main',
  turn_id: 'turn-1',
  actor_kind: 'main',
  reason: 'before_user_prompt',
  created_at: '2026-08-31T00:00:00Z',
}

describe('useCheckpoints', () => {
  it('tracks graph state and maps only main prompt checkpoints to turns', async () => {
    const request = vi.fn().mockResolvedValue({ nodes: [node], heads: { 'session-1': node.id } })
    const checkpoints = useCheckpoints(request)

    expect(checkpoints.state.value).toBe('idle')
    await expect(checkpoints.load('session-1')).resolves.toHaveLength(1)

    expect(checkpoints.state.value).toBe('ready')
    expect(checkpoints.getCheckpointForTurn('turn-1')).toBe('checkpoint-1')
    expect(checkpoints.checkpointTurnIds.value).toEqual(new Set(['turn-1']))
    expect(checkpoints.heads.value).toEqual({ 'session-1': 'checkpoint-1' })
    expect(request).toHaveBeenCalledWith('session.checkpoints.graph', { session_id: 'session-1' })
  })

  it('keeps empty graphs ready and exposes load errors for retry UI', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ nodes: [], heads: {} })
      .mockRejectedValueOnce(new Error('连接已断开'))
    const checkpoints = useCheckpoints(request)

    await checkpoints.load('session-1')
    expect(checkpoints.state.value).toBe('ready')

    await checkpoints.load('session-1')
    expect(checkpoints.state.value).toBe('error')
    expect(checkpoints.error.value).toBe('连接已断开')
  })

  it('routes restore and fork through the canonical operations', async () => {
    const request = vi.fn().mockResolvedValue({ operation_id: 'op-1', session_id: 'session-2' })
    const checkpoints = useCheckpoints(request)

    await checkpoints.restore('session-1', 'checkpoint-1', 'all')
    await checkpoints.fork('session-1', 'checkpoint-1')

    expect(request).toHaveBeenNthCalledWith(1, 'session.checkpoints.restore', {
      session_id: 'session-1', checkpoint_id: 'checkpoint-1', scope: 'all',
    })
    expect(request).toHaveBeenNthCalledWith(2, 'session.fork', {
      session_id: 'session-1', checkpoint_id: 'checkpoint-1',
    })
  })
})
