import { describe, expect, it } from 'vitest'
import {
  createCoreWorkbenchProjectionCache,
  hydrateSnapshot,
  selectCoreWorkbenchMessages,
  type CoreAppSnapshot,
} from '../src/appServer'

/**
 * Incremental projection cache contract:
 * - Same snapshot + shared cache → identical message/part object references
 *   (stable identity is what lets downstream components skip re-renders).
 * - A genuinely changed item only rebuilds the affected message; untouched
 *   messages keep their previous object identity.
 * - Request-state and submitting-set changes rebuild only affected parts.
 * - clear() resets everything.
 */

function baseSnapshot(): CoreAppSnapshot {
  return hydrateSnapshot({
    thread_id: 'thread-1',
    snapshot_seq: 3,
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 3,
      status: 'completed',
      item_order: ['item-1', 'item-2', 'item-3'],
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['item-1'] },
        'turn-2': { turn_id: 'turn-2', status: 'completed', items: ['item-2'] },
        'turn-3': { turn_id: 'turn-3', status: 'completed', items: ['item-3'] },
      },
      items: {
        'item-1': {
          item_id: 'item-1',
          turn_id: 'turn-1',
          kind: 'message',
          type: 'agentMessage',
          status: 'completed',
          content: 'answer one',
          payload: { type: 'agentMessage' },
        },
        'item-2': {
          item_id: 'item-2',
          turn_id: 'turn-2',
          kind: 'message',
          type: 'agentMessage',
          status: 'completed',
          content: 'answer two',
          payload: { type: 'agentMessage' },
        },
        'item-3': {
          item_id: 'item-3',
          turn_id: 'turn-3',
          kind: 'approval_request',
          type: 'serverRequest',
          status: 'waiting',
          content: 'approve the change?',
          payload: {
            type: 'serverRequest',
            request_id: 'req-1',
            title: '审批',
          },
        },
      },
      requests: {
        'req-1': { request_id: 'req-1', status: 'pending' },
      },
    },
  })
}

function withUpdatedItem(snapshot: CoreAppSnapshot, itemId: string, patch: Record<string, unknown>): CoreAppSnapshot {
  const core = snapshot.core!
  const items = { ...core.items }
  items[itemId] = { ...items[itemId], ...patch } as typeof items[string]
  return { ...snapshot, core: { ...core, items } }
}

function withResolvedRequest(snapshot: CoreAppSnapshot): CoreAppSnapshot {
  const core = snapshot.core!
  return {
    ...snapshot,
    core: {
      ...core,
      requests: { ...core.requests, 'req-1': { request_id: 'req-1', status: 'resolved', decision: 'approve_once' } },
    },
  }
}

function messageById(messages: { id: string }[], id: string) {
  const message = messages.find(m => m.id === id)
  expect(message, `message ${id} present`).toBeDefined()
  return message!
}

describe('incremental workbench projection cache', () => {
  it('reuses identical message and part references for an unchanged snapshot', () => {
    const cache = createCoreWorkbenchProjectionCache()
    const options = { source: 'core_app_server', active: false }
    const snapshot = baseSnapshot()

    const first = selectCoreWorkbenchMessages(snapshot, options, cache)
    const second = selectCoreWorkbenchMessages(snapshot, options, cache)

    expect(second.length).toBe(first.length)
    for (const msg of first) {
      expect(messageById(second, msg.id)).toBe(msg)
      const parts = messageById(second, msg.id).parts!
      msg.parts!.forEach((part, index) => {
        expect(parts[index]).toBe(part)
      })
    }
  })

  it('rebuilds only the changed message when one item updates; untouched messages keep identity', () => {
    const cache = createCoreWorkbenchProjectionCache()
    const options = { source: 'core_app_server', active: false }
    const snapshot = baseSnapshot()

    const before = selectCoreWorkbenchMessages(snapshot, options, cache)
    const after = selectCoreWorkbenchMessages(
      withUpdatedItem(snapshot, 'item-2', { content: 'answer two (v2)' }),
      options,
      cache,
    )

    expect(messageById(after, 'assistant:turn-2')).not.toBe(messageById(before, 'assistant:turn-2'))
    expect(messageById(after, 'assistant:turn-1')).toBe(messageById(before, 'assistant:turn-1'))
    expect(messageById(after, 'assistant:turn-3')).toBe(messageById(before, 'assistant:turn-3'))
    expect(messageById(after, 'assistant:turn-1').parts![0])
      .toBe(messageById(before, 'assistant:turn-1').parts![0])
  })

  it('rebuilds only approval parts when the request state changes', () => {
    const cache = createCoreWorkbenchProjectionCache()
    const options = { source: 'core_app_server', active: false }
    const snapshot = baseSnapshot()

    const before = selectCoreWorkbenchMessages(snapshot, options, cache)
    const after = selectCoreWorkbenchMessages(withResolvedRequest(snapshot), options, cache)

    const beforeApproval = messageById(before, 'assistant:turn-3').parts![0]
    const afterApproval = messageById(after, 'assistant:turn-3').parts![0]
    expect(afterApproval).not.toBe(beforeApproval)
    expect(afterApproval.status).toBe('completed')
    expect(messageById(after, 'assistant:turn-1')).toBe(messageById(before, 'assistant:turn-1'))
    expect(messageById(after, 'assistant:turn-2')).toBe(messageById(before, 'assistant:turn-2'))
  })

  it('rebuilds a part while the submitting set mutates in place (same Set reference)', () => {
    const cache = createCoreWorkbenchProjectionCache()
    const submitting = new Set<string>()
    const options = { source: 'core_app_server', active: false, submittingApprovalRequestIds: submitting }
    const snapshot = baseSnapshot()

    const before = selectCoreWorkbenchMessages(snapshot, options, cache)
    submitting.add('req-1')
    const after = selectCoreWorkbenchMessages(snapshot, options, cache)

    const beforeApproval = messageById(before, 'assistant:turn-3').parts![0]
    const afterApproval = messageById(after, 'assistant:turn-3').parts![0]
    expect(afterApproval).not.toBe(beforeApproval)
    expect(afterApproval.status).toBe('running')
    expect(messageById(after, 'assistant:turn-1')).toBe(messageById(before, 'assistant:turn-1'))
  })

  it('clears all cached references', () => {
    const cache = createCoreWorkbenchProjectionCache()
    const options = { source: 'core_app_server', active: false }
    const snapshot = baseSnapshot()

    const before = selectCoreWorkbenchMessages(snapshot, options, cache)
    cache.clear()
    const after = selectCoreWorkbenchMessages(snapshot, options, cache)

    expect(messageById(after, 'assistant:turn-1')).not.toBe(messageById(before, 'assistant:turn-1'))
  })

  it('never reuses messages across different snapshots/threads without a clear', () => {
    const cache = createCoreWorkbenchProjectionCache()
    const options = { source: 'core_app_server', active: false }
    const threadOne = baseSnapshot()
    const threadTwo = hydrateSnapshot({ ...baseSnapshot(), thread_id: 'thread-2', snapshot_seq: 1 })

    const one = selectCoreWorkbenchMessages(threadOne, options, cache)
    const two = selectCoreWorkbenchMessages(threadTwo, options, cache)

    expect(messageById(two, 'assistant:turn-1')).not.toBe(messageById(one, 'assistant:turn-1'))
    expect(messageById(two, 'assistant:turn-1').content).toBe(messageById(one, 'assistant:turn-1').content)
  })
})
