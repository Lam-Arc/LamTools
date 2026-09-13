import { describe, expect, it } from 'vitest'
import {
  createCoreWorkbenchProjectionCache,
  hydrateSnapshot,
  selectCoreWorkbenchMessagesWindow,
  type CoreAppItem,
  type CoreAppSnapshot,
  type CoreAppTurn,
  type CoreRuntimeItem,
  type CoreRuntimeTurn,
} from '../src/appServer'

function snapshotWithTurns(count: number): CoreAppSnapshot {
  const itemOrder: string[] = []
  const turns: Record<string, CoreRuntimeTurn> = {}
  const items: Record<string, CoreRuntimeItem> = {}
  for (let i = 1; i <= count; i += 1) {
    itemOrder.push(`item-${i}`)
    turns[`turn-${i}`] = { turn_id: `turn-${i}`, status: 'completed', items: [`item-${i}`] }
    items[`item-${i}`] = {
      item_id: `item-${i}`,
      turn_id: `turn-${i}`,
      kind: 'message',
      type: 'agentMessage',
      status: 'completed',
      content: `answer ${i}`,
      payload: { type: 'agentMessage' },
    }
  }
  return hydrateSnapshot({
    thread_id: 'thread-window',
    snapshot_seq: count,
    core: {
      thread_id: 'thread-window',
      snapshot_seq: count,
      status: 'completed',
      item_order: itemOrder,
      turns,
      items,
    },
  })
}

function snapshotWithUserAssistantTurns(count: number): CoreAppSnapshot {
  const itemOrder: string[] = []
  const topItems: Record<string, CoreAppItem> = {}
  const coreOrder: string[] = []
  const coreItems: Record<string, CoreRuntimeItem> = {}
  const turns: Record<string, CoreAppTurn> = {}
  for (let i = 1; i <= count; i += 1) {
    const turnId = `turn-${i}`
    const userId = `user-${i}`
    const assistantId = `assistant-${i}`
    itemOrder.push(userId)
    coreOrder.push(assistantId)
    topItems[userId] = {
      item_id: userId,
      turn_id: turnId,
      seq: i * 2 - 1,
      type: 'userMessage',
      content: [{ type: 'text', text: `question ${i}` }],
    }
    coreItems[assistantId] = {
      item_id: assistantId,
      turn_id: turnId,
      seq: i * 2,
      kind: 'message',
      type: 'agentMessage',
      status: 'completed',
      content: `answer ${i}`,
      payload: { type: 'agentMessage' },
    }
    turns[turnId] = { turn_id: turnId, status: 'completed', items: [assistantId] }
  }
  return hydrateSnapshot({
    thread_id: 'thread-window-pairs',
    snapshot_seq: count * 2,
    items: topItems,
    item_order: itemOrder,
    turns,
    core: {
      thread_id: 'thread-window-pairs',
      snapshot_seq: count * 2,
      status: 'completed',
      item_order: coreOrder,
      turns,
      items: coreItems,
    },
  })
}

describe('workbench projection history window', () => {
  it('returns all messages when no tailWindow is set', () => {
    const snapshot = snapshotWithTurns(5)
    const { messages, total, startIndex } = selectCoreWorkbenchMessagesWindow(snapshot, { active: false })
    expect(total).toBe(5)
    expect(startIndex).toBe(0)
    expect(messages.map(m => m.id)).toEqual([
      'assistant:turn-1',
      'assistant:turn-2',
      'assistant:turn-3',
      'assistant:turn-4',
      'assistant:turn-5',
    ])
  })

  it('projects only the most recent N messages with a tailWindow', () => {
    const snapshot = snapshotWithTurns(5)
    const { messages, total, startIndex } = selectCoreWorkbenchMessagesWindow(
      snapshot,
      { active: false, tailWindow: 2 },
    )
    expect(total).toBe(5)
    expect(startIndex).toBe(3)
    expect(messages.map(m => m.id)).toEqual(['assistant:turn-4', 'assistant:turn-5'])
    expect(messages[0].content).toBe('answer 4')
    expect(messages[1].content).toBe('answer 5')
  })

  it('clamps tailWindow larger than the message count', () => {
    const snapshot = snapshotWithTurns(3)
    const { messages, startIndex } = selectCoreWorkbenchMessagesWindow(
      snapshot,
      { active: false, tailWindow: 100 },
    )
    expect(startIndex).toBe(0)
    expect(messages).toHaveLength(3)
  })

  it('widens an assistant boundary to retain its preceding user message', () => {
    const { messages, total, startIndex } = selectCoreWorkbenchMessagesWindow(
      snapshotWithUserAssistantTurns(3),
      { active: false, tailWindow: 3 },
    )

    expect(total).toBe(6)
    expect(startIndex).toBe(2)
    expect(messages.map(message => [message.role, message.content])).toEqual([
      ['user', 'question 2'],
      ['assistant', 'answer 2'],
      ['user', 'question 3'],
      ['assistant', 'answer 3'],
    ])
  })

  it('projects complete turns and pages them ten turns at a time', () => {
    const { messages, total, startIndex } = selectCoreWorkbenchMessagesWindow(
      snapshotWithUserAssistantTurns(12),
      { active: false, tailTurns: 10 },
    )

    expect(total).toBe(24)
    expect(startIndex).toBe(4)
    expect(messages).toHaveLength(20)
    expect(messages[0]?.content).toBe('question 3')
    expect(messages[1]?.content).toBe('answer 3')
    expect(messages.at(-2)?.content).toBe('question 12')
    expect(messages.at(-1)?.content).toBe('answer 12')
  })

  it('keeps windowed message identity stable and only builds newly revealed ones', () => {
    const snapshot = snapshotWithTurns(5)
    const cache = createCoreWorkbenchProjectionCache()
    const options = { source: 'core_app_server', active: false }

    const small = selectCoreWorkbenchMessagesWindow(snapshot, { ...options, tailWindow: 2 }, cache)
    const wide = selectCoreWorkbenchMessagesWindow(snapshot, { ...options, tailWindow: 4 }, cache)

    // Messages inside the small window keep identical references after widening.
    const smallLatest = small.messages[small.messages.length - 1]
    const wideLatest = wide.messages[wide.messages.length - 1]
    expect(wideLatest).toBe(smallLatest)

    // Newly revealed history is correctly projected.
    expect(wide.messages.map(m => m.id)).toEqual([
      'assistant:turn-2',
      'assistant:turn-3',
      'assistant:turn-4',
      'assistant:turn-5',
    ])
    expect(wide.messages[0].content).toBe('answer 2')
  })

  it('recomputes startIndex when the snapshot grows (new turns arrive)', () => {
    const cache = createCoreWorkbenchProjectionCache()
    const options = { active: false, tailWindow: 2 }

    const small = selectCoreWorkbenchMessagesWindow(snapshotWithTurns(4), options, cache)
    expect(small.startIndex).toBe(2)
    expect(small.total).toBe(4)

    const grown = selectCoreWorkbenchMessagesWindow(snapshotWithTurns(6), options, cache)
    expect(grown.startIndex).toBe(4)
    expect(grown.total).toBe(6)
    expect(grown.messages.map(m => m.id)).toEqual(['assistant:turn-5', 'assistant:turn-6'])
  })
})
