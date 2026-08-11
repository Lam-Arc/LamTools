import { describe, expect, it } from 'vitest'
import { selectChatMessages } from '../src/appServer'
import type { CoreAppSnapshot } from '../src/appServer'
import { hydrateSnapshot } from '../src/appServer'

const T1 = '2b34c6365779499d91b449d8c1fdb2e5:turn:1f40a07b9825'
const T2 = '2b34c6365779499d91b449d8c1fdb2e5:turn:bbbbbbbbbbbb'

function snap(extra: Partial<CoreAppSnapshot> & { core: NonNullable<CoreAppSnapshot['core']> }) {
  return hydrateSnapshot({
    thread_id: '2b34c6365779499d91b449d8c1fdb2e5',
    snapshot_seq: 30,
    status: 'running',
    seen_event_ids: [],
    turns: {}, items: {}, item_order: [], queue: [], requests: {}, artifacts: {},
    ...extra,
  } satisfies CoreAppSnapshot)
}

describe('real-seq interleaving', () => {
  it('B is always before C when both carry envelope seq', () => {
    const s = snap({
      item_order: [`${T1}:user`, `${T2}:user`],
      items: {
        [`${T1}:user`]: { item_id: `${T1}:user`, turn_id: T1, type: 'userMessage', status: 'completed', seq: 2, content: [{ type: 'text', text: '旧问题' }] },
        [`${T2}:user`]: { item_id: `${T2}:user`, turn_id: T2, type: 'userMessage', status: 'completed', seq: 21, content: [{ type: 'text', text: '新问题' }] },
      },
      core: {
        thread_id: '2b34c6365779499d91b449d8c1fdb2e5', snapshot_seq: 30, status: 'running',
        item_order: ['old-reason', 'old-text', 'running-status', 'new-reason'],
        turns: {
          [T1]: { turn_id: T1, status: 'completed', items: ['old-reason', 'old-text'] },
          [T2]: { turn_id: T2, status: 'running', items: ['running-status', 'new-reason'] },
        },
        items: {
          'old-reason': { item_id: 'old-reason', turn_id: T1, kind: 'thinking', status: 'completed', seq: 3, payload: { type: 'reasoning', content: '旧思考' } },
          'old-text': { item_id: 'old-text', turn_id: T1, kind: 'message', status: 'completed', seq: 4, payload: { type: 'agentMessage', content: '旧回答' } },
          'running-status': { item_id: 'running-status', turn_id: T2, kind: 'status', status: 'running', seq: 22, payload: { type: 'status', content: 'running' } },
          'new-reason': { item_id: 'new-reason', turn_id: T2, kind: 'thinking', status: 'running', seq: 23, payload: { type: 'reasoning', content: '' } },
        },
      },
    })

    const messages = selectChatMessages(s)
    const order = messages.map(m => {
      const firstPartType = m.parts[0]?.type ?? ''
      return `${m.role}:${firstPartType}:${m.id.slice(-12)}`
    })
    expect(order).toEqual([
      `user::${T1.slice(-12)}`,
      'assistant:reasoning:old-reason',
      `user::${T2.slice(-12)}`,
      'assistant:reasoning:new-reason',
    ])
  })

  it('B.seq=0 causes C to appear above B', () => {
    // Simulate what happens if item/started carries seq=0
    // (e.g. from a batch-relative field instead of envelope seq)
    const s = snap({
      item_order: [`${T1}:user`, `${T2}:user`],
      items: {
        [`${T1}:user`]: { item_id: `${T1}:user`, turn_id: T1, type: 'userMessage', status: 'completed', seq: 2, content: [{ type: 'text', text: '旧' }] },
        // B with seq=0 (wrong)
        [`${T2}:user`]: { item_id: `${T2}:user`, turn_id: T2, type: 'userMessage', status: 'completed', seq: 0, content: [{ type: 'text', text: '新' }] },
      },
      core: {
        thread_id: '2b34c6365779499d91b449d8c1fdb2e5', snapshot_seq: 30, status: 'running',
        item_order: ['running', 'reason'],
        turns: {
          [T1]: { turn_id: T1, status: 'completed', items: [] },
          [T2]: { turn_id: T2, status: 'running', items: ['running', 'reason'] },
        },
        items: {
          'running': { item_id: 'running', turn_id: T2, kind: 'status', status: 'running', seq: 22, payload: { type: 'status' } },
          'reason': { item_id: 'reason', turn_id: T2, kind: 'thinking', status: 'running', seq: 23, payload: { type: 'reasoning', content: '' } },
        },
      },
    })

    const messages = selectChatMessages(s)
    const order = messages.map(m => `${m.role}:${m.id.slice(-12)}`)
    // B@seq=0 → outerSeqAnchor = 0; core items@seq=22,23 → core first
    // So the new assistant appears ABOVE the user message
    const hasBug = order.findIndex(o => o.includes(T2.slice(-12))) > order.findIndex(o => o.startsWith('assistant'))
    expect(hasBug).toBe(true) // This proves seq=0 reproduces the bug
  })
})
