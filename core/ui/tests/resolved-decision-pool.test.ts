import { describe, expect, it } from 'vitest'
import { mergeResolvedRequestStates } from '../src/appServer/store.ts'
import { selectVisiblePendingDecisions } from '../src/appServer/pendingDecisions.ts'
import type { CoreAppInteraction, CoreAppSnapshot } from '../src/appServer/protocol.ts'

// user:“修”+(旧快照补入结束状态时同步移除卡片，保留其他卡片及顺序。)
function fixture(status = 'open'): CoreAppSnapshot {
  const cards: CoreAppInteraction[] = [
    { interaction_id: 'int-1', request_id: 'req-1', status: 'open', sequence: 1 },
    { interaction_id: 'int-2', request_id: 'req-2', status: 'open', sequence: 2 },
  ]
  return {
    thread_id: 'thread', snapshot_seq: 8, revision: 4,
    requests: { 'req-1': { request_id: 'req-1', status } },
    interactions: cards, decisions: cards,
    core: {
      thread_id: 'thread', snapshot_seq: 8,
      requests: { 'req-1': { request_id: 'req-1', status } },
      interactions: cards, decisions: cards,
    },
  } as CoreAppSnapshot
}

describe('stale snapshot decision pool repair', () => {
  it.each(['resolved', 'cancelled', 'expired'])('removes a %s card from all pool views', status => {
    const current = fixture()
    const incoming = {
      thread_id: 'thread', requests: { 'req-1': { request_id: 'req-1', status } },
    } as CoreAppSnapshot
    const merged = mergeResolvedRequestStates(current, incoming)!
    expect(merged).not.toBeNull()
    for (const pool of [merged.interactions, merged.decisions, merged.core?.interactions, merged.core?.decisions]) {
      expect(pool?.map(card => card.interaction_id)).toEqual(['int-2'])
      expect(pool?.[0]).toBe(current.interactions?.[1])
    }
    expect(selectVisiblePendingDecisions([], merged.core?.decisions)).toHaveLength(1)
    expect(merged.snapshot_seq).toBe(8)
    expect(current.interactions).toHaveLength(2)
  })

  it('also repairs a pool whose request was already resolved', () => {
    const current = fixture('resolved')
    const merged = mergeResolvedRequestStates(current, current)!
    expect(merged?.core?.decisions?.map(card => card.interaction_id)).toEqual(['int-2'])
  })

  it.each(['processing', 'deferred'])('does not treat %s as a terminal decision', status => {
    const current = fixture()
    const incoming = { thread_id: 'thread', requests: { 'req-1': { request_id: 'req-1', status } } } as CoreAppSnapshot
    expect(mergeResolvedRequestStates(current, incoming)).toBeNull()
  })
})
