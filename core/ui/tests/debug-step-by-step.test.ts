import { describe, expect, it } from 'vitest'
import { hydrateSnapshot, selectChatMessages } from '../src/appServer'
import type { CoreAppSnapshot } from '../src/appServer'

const T1 = 'session:turn:aaaa'
const T2 = 'session:turn:bbbb'

function historySnapshot(): CoreAppSnapshot {
  return hydrateSnapshot({
    thread_id: 't1', snapshot_seq: 10, status: 'completed',
    item_order: ['A:user'],
    items: { 'A:user': { item_id: 'A:user', turn_id: T1, type: 'userMessage', status: 'completed', seq: 2, content: [{ type: 'text', text: '旧问题' }] } },
    core: {
      thread_id: 't1', snapshot_seq: 10, status: 'completed', item_order: ['A:reason', 'A:text'],
      turns: { [T1]: { turn_id: T1, status: 'completed', items: ['A:reason', 'A:text'] } },
      items: {
        'A:reason': { item_id: 'A:reason', turn_id: T1, kind: 'thinking', status: 'completed', seq: 3, payload: { type: 'reasoning', content: '思考旧' } },
        'A:text': { item_id: 'A:text', turn_id: T1, kind: 'message', status: 'completed', seq: 4, payload: { type: 'agentMessage', content: '旧回答' } },
      },
    },
  })
}

describe('step-by-step', () => {
  it('tracks exact message order at each phase', () => {
    // Phase 1: resume with history
    let state = historySnapshot()
    let msgs = selectChatMessages(state).map(m => m.id)
    expect(msgs).toEqual(['A:user', `assistant:${T1}`])

    // Phase 2: turn/start response snapshot S1 (contains B, T2 running, no C yet)
    state = hydrateSnapshot({
      thread_id: 't1', snapshot_seq: 15, status: 'running',
      item_order: ['A:user', 'B:user'],
      items: {
        'A:user': { item_id: 'A:user', turn_id: T1, type: 'userMessage', status: 'completed', seq: 2, content: [{ type: 'text', text: '旧' }] },
        'B:user': { item_id: 'B:user', turn_id: T2, type: 'userMessage', status: 'completed', seq: 21, content: [{ type: 'text', text: '新问题' }] },
      },
      core: {
        thread_id: 't1', snapshot_seq: 15, status: 'running',
        item_order: ['A:reason', 'A:text', 'running-status'],
        turns: {
          [T1]: { turn_id: T1, status: 'completed', items: ['A:reason', 'A:text'] },
          [T2]: { turn_id: T2, status: 'running', items: ['running-status'] },
        },
        items: {
          'A:reason': { item_id: 'A:reason', turn_id: T1, kind: 'thinking', status: 'completed', seq: 3, payload: { type: 'reasoning', content: '' } },
          'A:text': { item_id: 'A:text', turn_id: T1, kind: 'message', status: 'completed', seq: 4, payload: { type: 'agentMessage', content: '答' } },
          'running-status': { item_id: 'running-status', turn_id: T2, kind: 'status', status: 'running', seq: 22, payload: { type: 'status', content: 'running' } },
        },
      },
    })
    msgs = selectChatMessages(state).map(m => m.id)
    // B is AFTER A's assistant, BEFORE the T2 segment — correct
    expect(msgs).toEqual([
      'A:user', `assistant:${T1}`,
      'B:user', `assistant:${T2}`,
    ])

    // Phase 3: first runItem arrives (reasoning, T2) — delta applied via core.items
    state = hydrateSnapshot({
      thread_id: 't1', snapshot_seq: 18, status: 'running',
      item_order: ['A:user', 'B:user'],
      items: {
        'A:user': { item_id: 'A:user', turn_id: T1, type: 'userMessage', status: 'completed', seq: 2, content: [{ type: 'text', text: '旧' }] },
        'B:user': { item_id: 'B:user', turn_id: T2, type: 'userMessage', status: 'completed', seq: 21, content: [{ type: 'text', text: '新' }] },
      },
      core: {
        thread_id: 't1', snapshot_seq: 18, status: 'running',
        item_order: ['A:reason', 'A:text', 'running-status', 'C:reason'],
        turns: {
          [T1]: { turn_id: T1, status: 'completed', items: ['A:reason', 'A:text'] },
          [T2]: { turn_id: T2, status: 'running', items: ['running-status', 'C:reason'] },
        },
        items: {
          'A:reason': { item_id: 'A:reason', turn_id: T1, kind: 'thinking', status: 'completed', seq: 3, payload: { type: 'reasoning', content: '' } },
          'A:text': { item_id: 'A:text', turn_id: T1, kind: 'message', status: 'completed', seq: 4, payload: { type: 'agentMessage', content: '答' } },
          'running-status': { item_id: 'running-status', turn_id: T2, kind: 'status', status: 'running', seq: 22, payload: { type: 'status' } },
          'C:reason': { item_id: 'C:reason', turn_id: T2, kind: 'thinking', status: 'running', seq: 23, payload: { type: 'reasoning', content: '' } },
        },
      },
    })
    msgs = selectChatMessages(state).map(m => m.id)
    // THIS is the key: B must be BEFORE the T2 assistant segment
    expect(msgs).toEqual([
      'A:user', `assistant:${T1}`,
      'B:user', `assistant:${T2}`,
    ])
  }, 10_000)
})
