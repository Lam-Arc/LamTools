import { describe, expect, it } from 'vitest'
import { applyCoreAppEvent, hydrateSnapshot, selectCoreQueuedInputs, selectQueueTray } from '../src'
import type { CoreAppEvent, CoreAppSnapshot } from '../src'

// user:“排队项可拖拽上下移动重新排序”+(重排序以 queue/itemReordered 事件落库，
//   客户端把它应用到快照并按 position 展示托盘；本轮结束后按新顺序分发)。
function queuedItem(id: string, seq: number): Record<string, unknown> {
  return { queue_item_id: id, status: 'queued', mode: 'next_turn', input: [{ type: 'text', text: id }], seq }
}

function snapshotWithQueue(queue: Record<string, unknown>[]): CoreAppSnapshot {
  return hydrateSnapshot({
    thread_id: 'thread-reorder',
    snapshot_seq: 10,
    queue,
  } as unknown as CoreAppSnapshot)
}

function reorderEvent(order: string[], seq = 11): CoreAppEvent {
  return {
    event_id: `evt-${seq}`,
    thread_id: 'thread-reorder',
    seq,
    method: 'queue/itemReordered',
    payload: { type: 'queue', order },
  } as unknown as CoreAppEvent
}

describe('queue item reorder', () => {
  it('applies queue/itemReordered by rewriting positions and snapshot order', () => {
    const snapshot = snapshotWithQueue([queuedItem('a', 1), queuedItem('b', 2), queuedItem('c', 3)])

    const reordered = applyCoreAppEvent(snapshot, reorderEvent(['c', 'a', 'b']))

    expect(reordered.queue?.map(item => item.queue_item_id)).toEqual(['c', 'a', 'b'])
    expect(reordered.queue?.map(item => item.position)).toEqual([0, 1, 2])
  })

  it('keeps unknown ids behind the ordered ones in their previous relative order', () => {
    const snapshot = snapshotWithQueue([queuedItem('a', 1), queuedItem('b', 2)])
    // 'late' 是重排序事件之后新排队的条目：它没有 position，按 seq 排在最后。
    const withLate = applyCoreAppEvent(snapshot, {
      event_id: 'evt-late', thread_id: 'thread-reorder', seq: 12, method: 'queue/itemAccepted',
      payload: { queue_item_id: 'late', status: 'queued', mode: 'next_turn', input: [{ type: 'text', text: 'late' }] },
    } as unknown as CoreAppEvent)

    const reordered = applyCoreAppEvent(withLate, reorderEvent(['b', 'a'], 13))

    expect(reordered.queue?.map(item => item.queue_item_id)).toEqual(['b', 'a', 'late'])
    expect(selectQueueTray(reordered).map(item => item.queue_item_id)).toEqual(['b', 'a', 'late'])
  })

  it('sorts the tray by position first and falls back to seq for legacy items', () => {
    // 旧快照：条目没有 position，保持原有 seq 顺序。
    const legacy = snapshotWithQueue([queuedItem('old-1', 5), queuedItem('old-2', 6)])
    expect(selectQueueTray(legacy).map(item => item.queue_item_id)).toEqual(['old-1', 'old-2'])

    // 重排序后 position 是第一排序键；没有 position 的条目按 seq 排在其后。
    const mixed = snapshotWithQueue([
      { ...queuedItem('first', 9), position: 0 },
      { ...queuedItem('second', 10), position: 1 },
      queuedItem('legacy', 11),
    ])
    expect(selectQueueTray(mixed).map(item => item.queue_item_id)).toEqual(['first', 'second', 'legacy'])
  })

  it('projects the reordered tray numbering into queued inputs', () => {
    const snapshot = snapshotWithQueue([queuedItem('a', 1), queuedItem('b', 2)])
    const reordered = applyCoreAppEvent(snapshot, reorderEvent(['b', 'a']))

    expect(selectCoreQueuedInputs(reordered).map(item => item.id)).toEqual(['b', 'a'])
    expect(selectCoreQueuedInputs(reordered).map(item => item.position)).toEqual([1, 2])
  })
})
