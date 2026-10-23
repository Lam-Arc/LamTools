import { describe, expect, it } from 'vitest'
import { mergeResolvedRequestStates } from '../src/appServer/store.ts'
import type { CoreAppSnapshot } from '../src/appServer/protocol.ts'

function snapshot(
  requests: Record<string, { request_id: string; status: string; decision?: string }>,
): CoreAppSnapshot {
  return {
    thread_id: 'thread-1',
    snapshot_seq: 5,
    revision: 3,
    status: 'waiting',
    items: {},
    item_order: [],
    requests,
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 5,
      revision: 3,
      status: 'waiting',
      turns: {},
      items: {},
      item_order: [],
      requests,
      seen_event_ids: [],
    },
  } as unknown as CoreAppSnapshot
}

describe('mergeResolvedRequestStates', () => {
  it('adopts a resolved request from a stale snapshot', () => {
    const current = snapshot({
      'req-1': { request_id: 'req-1', status: 'open' },
    })
    const incoming = snapshot({
      'req-1': { request_id: 'req-1', status: 'resolved', decision: 'approve_once' },
    })

    const merged = mergeResolvedRequestStates(current, incoming)

    expect(merged).not.toBeNull()
    expect(merged?.core?.requests?.['req-1']?.status).toBe('resolved')
    expect(merged?.core?.requests?.['req-1']?.decision).toBe('approve_once')
    // The rest of the thread is not replaced by the stale snapshot.
    expect(merged?.snapshot_seq).toBe(current.snapshot_seq)
  })

  it('never reopens or invents a request', () => {
    const current = snapshot({
      'req-1': { request_id: 'req-1', status: 'resolved' },
      'req-2': { request_id: 'req-2', status: 'open' },
    })
    const incoming = snapshot({
      'req-1': { request_id: 'req-1', status: 'open' },
      'req-2': { request_id: 'req-2', status: 'resolved' },
      'req-new': { request_id: 'req-new', status: 'resolved' },
    })

    const merged = mergeResolvedRequestStates(current, incoming)

    expect(merged?.core?.requests?.['req-1']?.status).toBe('resolved')
    expect(merged?.core?.requests?.['req-2']?.status).toBe('resolved')
    expect(merged?.core?.requests?.['req-new']).toBeUndefined()
  })

  it('returns null when nothing new was resolved', () => {
    const current = snapshot({ 'req-1': { request_id: 'req-1', status: 'open' } })
    const incoming = snapshot({ 'req-1': { request_id: 'req-1', status: 'open' } })

    expect(mergeResolvedRequestStates(current, incoming)).toBeNull()
  })
})

describe('decision pool lifecycle events', () => {
  it('moves a card from processing to ending and removes it', async () => {
    const { applyCoreAppEvent } = await import('../src/appServer/store.ts')
    const base = {
      thread_id: 'thread-1',
      snapshot_seq: 0,
      revision: 0,
      items: {},
      item_order: [],
      requests: {},
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 0,
        revision: 0,
        items: {},
        item_order: [],
        requests: {},
        seen_event_ids: [],
      },
    } as unknown as CoreAppSnapshot
    const processing = applyCoreAppEvent(base, {
      method: 'core/runItem',
      thread_id: 'thread-1',
      seq: 1,
      payload: {
        item_id: 'dec-a',
        event_id: 'evt-processing',
        kind: 'interaction_update',
        payload: {
          request_id: 'dec-a',
          interaction_id: 'dec-a',
          kind: 'question',
          state: 'processing',
          lifecycle: 'processing',
          status: 'processing',
          decision_id: 'dec_hash',
          sequence: 3,
          delivered_by: 'agent:reader',
          project_id: 'project-1',
        },
      },
    } as unknown as Parameters<typeof applyCoreAppEvent>[1])
    expect(processing.core?.requests?.['dec-a']?.status).toBe('processing')
    expect(processing.core?.interactions?.[0]?.lifecycle).toBe('processing')
    expect(processing.core?.interactions?.[0]?.decision_id).toBe('dec_hash')

    const ending = applyCoreAppEvent(processing, {
      method: 'core/runItem',
      thread_id: 'thread-1',
      seq: 2,
      payload: {
        item_id: 'dec-a',
        event_id: 'evt-ending',
        kind: 'approval_response',
        payload: {
          request_id: 'dec-a',
          interaction_id: 'dec-a',
          state: 'ending',
          lifecycle: 'ending',
          status: 'resolved',
          decision: 'approve_once',
        },
      },
    } as unknown as Parameters<typeof applyCoreAppEvent>[1])
    expect(ending.core?.requests?.['dec-a']?.status).toBe('resolved')
    expect(ending.core?.interactions ?? []).toEqual([])
  })
})
