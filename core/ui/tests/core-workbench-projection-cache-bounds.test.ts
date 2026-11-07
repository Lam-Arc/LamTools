import { describe, expect, it } from 'vitest'
import {
  createCoreWorkbenchProjectionCache,
  hydrateSnapshot,
  selectCoreWorkbenchMessages,
  type CoreAppSnapshot,
} from '../src/appServer'

/**
 * user:“内存：长时间使用保持有界，不随浏览过的消息数量无限增长”
 *
 * The projection cache is keyed by item/message id and only ever grows as the
 * user browses history. Without a bound, paging back through a long session
 * keeps a second full copy of every message it ever projected. These tests pin
 * the bound: the oldest insertions are dropped, the newest survive, and a
 * dropped entry simply gets rebuilt on the next projection.
 */

function snapshotWithTurns(turns: number): CoreAppSnapshot {
  const itemOrder: string[] = []
  const turnsMap: Record<string, { turn_id: string; status: string; items: string[] }> = {}
  for (let index = 0; index < turns; index += 1) {
    const turnId = `turn-${index}`
    const itemId = `${turnId}:text`
    itemOrder.push(itemId)
    turnsMap[turnId] = { turn_id: turnId, status: 'completed', items: [itemId] }
  }
  return hydrateSnapshot({
    thread_id: 'thread-1',
    snapshot_seq: turns,
    core: {
      thread_id: 'thread-1',
      snapshot_seq: turns,
      status: 'completed',
      item_order: itemOrder,
      items: Object.fromEntries(itemOrder.map((itemId, index) => [itemId, {
        item_id: itemId,
        turn_id: `turn-${index}`,
        type: 'agentMessage',
        seq: index + 1,
        content: `answer ${index}`,
        payload: { type: 'agentMessage', content: `answer ${index}` },
      }])),
      turns: turnsMap,
      requests: {},
      artifacts: {},
    },
    items: {},
    item_order: [],
    turns: {},
    requests: {},
    queue: [],
    artifacts: {},
    status: 'completed',
  } as never)
}

describe('projection cache bounds', () => {
  it('drops the oldest entries once a map exceeds its cap', () => {
    const cache = createCoreWorkbenchProjectionCache()
    for (let index = 0; index < 2_600; index += 1) {
      cache.messagesById.set(`message-${index}`, {
        fingerprint: [index],
        message: { id: `message-${index}` } as never,
      })
    }
    cache.prune()
    expect(cache.messagesById.size).toBe(2_000)
    // The newest insertions survive; the oldest are evicted.
    expect(cache.messagesById.has('message-2599')).toBe(true)
    expect(cache.messagesById.has('message-0')).toBe(false)
  })

  it('bounds every cache map, not just the message cache', () => {
    const cache = createCoreWorkbenchProjectionCache()
    for (let index = 0; index < 9_000; index += 1) {
      cache.itemsApp.set({ item_id: `item-${index}` } as never, { item_id: `item-${index}` } as never)
    }
    cache.prune()
    expect(cache.itemsApp.size).toBe(8_000)
  })

  it('keeps projecting correctly after an eviction', () => {
    const cache = createCoreWorkbenchProjectionCache()
    const snapshot = snapshotWithTurns(6)
    const first = selectCoreWorkbenchMessages(snapshot, {}, cache)
    expect(first.length).toBe(6)
    cache.clear()
    const rebuilt = selectCoreWorkbenchMessages(snapshot, {}, cache)
    expect(rebuilt.map(message => message.id)).toEqual(first.map(message => message.id))
    expect(rebuilt.map(message => message.content)).toEqual(first.map(message => message.content))
  })

  it('pruning does not change the projected messages of the current window', () => {
    const cache = createCoreWorkbenchProjectionCache()
    const snapshot = snapshotWithTurns(12)
    const before = selectCoreWorkbenchMessages(snapshot, { tailTurns: 4 }, cache)
    // Force a prune with entries that are not part of this window.
    for (let index = 0; index < 3_000; index += 1) {
      cache.messagesById.set(`stale-${index}`, { fingerprint: [index], message: { id: `stale-${index}` } as never })
    }
    cache.prune()
    const after = selectCoreWorkbenchMessages(snapshot, { tailTurns: 4 }, cache)
    expect(after.map(message => message.id)).toEqual(before.map(message => message.id))
  })
})
