import { describe, expect, it } from 'vitest'
import { mergeCoreNewestSnapshot, type CoreAppSnapshot } from '../src/appServer'

function snapshot(
  ids: string[],
  seqStart: number,
  extra: Record<string, unknown> = {},
): CoreAppSnapshot {
  const items: Record<string, Record<string, unknown>> = {}
  const order: string[] = []
  const turns: Record<string, { turn_id: string; status: string; items: string[] }> = {}
  ids.forEach((id, index) => {
    const turnId = `turn-${Math.floor(index / 2)}`
    items[id] = { item_id: id, turn_id: turnId, seq: seqStart + index, type: 'message', content: [] }
    order.push(id)
    turns[turnId] = turns[turnId] ?? { turn_id: turnId, status: 'completed', items: [] }
    turns[turnId].items.push(id)
  })
  return {
    thread_id: 'thread-1',
    snapshot_seq: seqStart + ids.length,
    revision: 1,
    items: {},
    item_order: [],
    turns: {},
    core: {
      thread_id: 'thread-1',
      snapshot_seq: seqStart + ids.length,
      revision: 1,
      items,
      item_order: order,
      turns,
    },
    ...extra,
  } as unknown as CoreAppSnapshot
}

describe('mergeCoreNewestSnapshot', () => {
  it('keeps older items and adopts the page scalars', () => {
    const current = snapshot(['a', 'b', 'c', 'd'], 1, {
      revision: 5,
      snapshot_seq: 10,
      status: 'cancelled',
    })
    const page = snapshot(['e', 'f'], 11, {
      revision: 6,
      snapshot_seq: 12,
      status: 'running',
    })
    ;(page as unknown as { history_page: unknown }).history_page = { has_more: true }

    const merged = mergeCoreNewestSnapshot(current, page)

    // The page is the newest state, so its scalars win.
    expect(merged.revision).toBe(6)
    expect(merged.snapshot_seq).toBe(12)
    expect((merged as unknown as { status: string }).status).toBe('running')
    // Items older than the page survive the merge.
    expect((merged.core as { item_order: string[] }).item_order).toEqual([
      'a', 'b', 'c', 'd', 'e', 'f',
    ])
    expect((merged.core as { items: Record<string, unknown> }).items.e).toBeTruthy()
    expect((merged as unknown as { history_page: unknown }).history_page).toEqual({ has_more: true })
  })

  it('does not duplicate items that appear on both sides', () => {
    const current = snapshot(['a', 'b', 'c'], 1)
    const page = snapshot(['b', 'c', 'd'], 2)

    const merged = mergeCoreNewestSnapshot(current, page)

    expect((merged.core as { item_order: string[] }).item_order).toEqual(['a', 'b', 'c', 'd'])
  })
})
