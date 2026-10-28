import { describe, expect, it, vi } from 'vitest'
import * as selectors from '../src/appServer/selectors'
import { hydrateSnapshot } from '../src/appServer/snapshot'
import { createCoreWorkbenchProjectionCache, selectCoreWorkbenchMessagesWindow } from '../src/appServer/workbenchProjection'

// user:“修，不要出错”+(同一不可变快照只整理一次历史；状态、分页与新快照必须正确更新)。
describe('send-time projection reuse', () => {
  it('refreshes attachments when attachment metadata changes', () => {
    const snapshot = hydrateSnapshot({ thread_id: 'attachment', snapshot_seq: 1, item_order: ['user'], items: {
      user: { item_id: 'user', turn_id: 'turn', type: 'userMessage', content: [
        { type: 'text', text: 'Inspect' }, { type: 'attachment', attachment_id: 'file', filename: 'before.txt' },
      ] },
    } })
    const cache = createCoreWorkbenchProjectionCache()
    const before = selectCoreWorkbenchMessagesWindow(snapshot, {}, cache)
    const next = { ...snapshot, items: { ...snapshot.items, user: {
      ...snapshot.items!.user, content: [{ type: 'text', text: 'Inspect' }, { type: 'attachment', attachment_id: 'file', filename: 'after.txt' }],
    } } }
    const after = selectCoreWorkbenchMessagesWindow(next, {}, cache)
    expect(after.messages[0]).not.toBe(before.messages[0])
    expect(after.messages[0].parts?.find(part => part.partType === 'attachment')?.label).toBe('after.txt')
  })

  it('preserves historical user and assistant identities when a new send snapshot arrives', () => {
    const snapshot = hydrateSnapshot({ thread_id: 'mixed', snapshot_seq: 2,
      item_order: ['user'], items: { user: { item_id: 'user', turn_id: 'old', type: 'userMessage', content: [{ type: 'text', text: 'Question' }] } },
      core: { thread_id: 'mixed', snapshot_seq: 2, status: 'completed', item_order: ['answer'], items: {
        answer: { item_id: 'answer', turn_id: 'old', kind: 'message', type: 'agentMessage', status: 'completed', content: 'Answer', payload: { type: 'agentMessage' } },
      } },
    })
    const cache = createCoreWorkbenchProjectionCache()
    const before = selectCoreWorkbenchMessagesWindow(snapshot, {}, cache)
    const next = { ...snapshot, snapshot_seq: 3, item_order: [...snapshot.item_order!, 'new-user'], items: {
      ...snapshot.items, 'new-user': { item_id: 'new-user', turn_id: 'new', type: 'userMessage', content: [{ type: 'text', text: 'Next question' }] },
    } }
    const after = selectCoreWorkbenchMessagesWindow(next, {}, cache)
    expect(after.messages.map(message => message.content)).toEqual(['Question', 'Answer', 'Next question'])
    expect(after.messages[0]).toBe(before.messages[0])
    expect(after.messages[1]).toBe(before.messages[1])
  })

  it('keeps historical message identities when send-time shallow thinking changes', () => {
    const snapshot = hydrateSnapshot({ thread_id: 'identity', snapshot_seq: 2, core: {
      thread_id: 'identity', snapshot_seq: 2, status: 'running', item_order: ['old', 'current'],
      items: Object.fromEntries(['old', 'current'].map(id => [id, {
        item_id: id, turn_id: `turn-${id}`, kind: 'message', type: 'agentMessage', status: 'completed',
        content: id, payload: { type: 'agentMessage' },
      }])),
    } })
    const cache = createCoreWorkbenchProjectionCache()
    const before = selectCoreWorkbenchMessagesWindow(snapshot, { active: false, shallowThinkingPending: false }, cache)
    const sending = selectCoreWorkbenchMessagesWindow(snapshot, { active: true, shallowThinkingPending: true }, cache)
    expect(sending.messages[0]).toBe(before.messages[0])
    expect(sending.messages[1].metadata?.shallowThinkingPending).toBe(true)
    const streamed = selectCoreWorkbenchMessagesWindow(snapshot, { active: true, shallowThinkingPending: false }, cache)
    expect(streamed.messages[0]).toBe(before.messages[0])
    expect(streamed.messages[1].metadata?.shallowThinkingPending).toBeUndefined()
  })

  it('matches uncached projection when paging history or changing approval and live options', () => {
    const snapshot = hydrateSnapshot({ thread_id: 'paging', snapshot_seq: 3, core: {
      thread_id: 'paging', snapshot_seq: 3, status: 'running', item_order: ['a', 'b', 'c'],
      items: Object.fromEntries(['a', 'b', 'c'].map(id => [id, {
        item_id: id, turn_id: `turn-${id}`, kind: 'message', type: 'agentMessage', status: 'completed',
        content: `Answer ${id}`, payload: { type: 'agentMessage' },
      }])),
    } })
    const cache = createCoreWorkbenchProjectionCache()
    for (const options of [
      { tailTurns: 1, active: false }, { tailTurns: 3, active: true },
      { tailTurns: 2, shallowThinkingPending: true, submittingApprovalRequestIds: new Set(['request']) },
    ]) {
      expect(selectCoreWorkbenchMessagesWindow(snapshot, options, cache))
        .toEqual(selectCoreWorkbenchMessagesWindow(snapshot, options))
    }
  })

  it('reuses history selection across UI option changes, and invalidates on new snapshots and clear', () => {
    const spy = vi.spyOn(selectors, 'selectChatMessages')
    try {
      const snapshot = hydrateSnapshot({ thread_id: 'test', snapshot_seq: 1, core: {
        thread_id: 'test', snapshot_seq: 1, status: 'completed', item_order: ['a'],
        items: { a: { item_id: 'a', turn_id: 't', kind: 'message', type: 'agentMessage', status: 'completed', content: 'Before', payload: { type: 'agentMessage' } } },
      } })
      const cache = createCoreWorkbenchProjectionCache()
      const first = selectCoreWorkbenchMessagesWindow(snapshot, { active: false, tailTurns: 1 }, cache)
      const live = selectCoreWorkbenchMessagesWindow(snapshot, { active: true, tailTurns: 10 }, cache)
      expect(spy).toHaveBeenCalledTimes(1)
      expect(first.messages[0].metadata?.live).toBeUndefined()
      expect(live.messages[0].metadata?.live).toBe(true)
      const next = { ...snapshot, core: { ...snapshot.core!, items: {
        ...snapshot.core!.items, a: { ...snapshot.core!.items!.a, content: 'After' },
      } } }
      const changed = selectCoreWorkbenchMessagesWindow(next, {}, cache)
      expect(spy).toHaveBeenCalledTimes(2)
      expect(changed.messages[0].content).toBe('After')
      cache.clear()
      selectCoreWorkbenchMessagesWindow(next, {}, cache)
      expect(spy).toHaveBeenCalledTimes(3)
    } finally { spy.mockRestore() }
  })
})
