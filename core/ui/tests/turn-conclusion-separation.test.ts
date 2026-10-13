import { describe, expect, it } from 'vitest'
import { hydrateSnapshot, selectCoreWorkbenchMessages } from '../src/appServer'
import type { CoreAppSnapshot, CoreRuntimeItem } from '../src/appServer'

/**
 * A session where turn 1 concluded, and a later turn 2 ran afterwards (the
 * shape a member wake-up continuation produces). The later turn must never be
 * folded into the earlier turn's block, and the earlier conclusion must keep
 * reading as that turn's conclusion.
 */
function twoTurnSnapshot(turn2Id = 'turn-2'): CoreAppSnapshot {
  const item = (
    item_id: string,
    turn_id: string,
    kind: string,
    payload: Record<string, unknown>,
  ): CoreRuntimeItem => ({ item_id, turn_id, kind, status: 'completed', payload })

  const turns = {
    'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['r1', 'a1'] },
    [turn2Id]: { turn_id: turn2Id, status: 'completed', items: ['r2', 'a2'] },
  }
  return hydrateSnapshot({
    thread_id: 'thread-two-turns',
    snapshot_seq: 9,
    status: 'completed',
    turns,
    core: {
      thread_id: 'thread-two-turns',
      snapshot_seq: 9,
      status: 'completed',
      turns,
      item_order: ['r1', 'a1', 'r2', 'a2'],
      items: {
        r1: item('r1', 'turn-1', 'thinking', { type: 'reasoning', content: '第一轮的过程' }),
        a1: item('a1', 'turn-1', 'message', { type: 'agentMessage', content: '第一轮的结论。' }),
        r2: item('r2', turn2Id, 'thinking', { type: 'reasoning', content: '第二轮的过程' }),
        a2: item('a2', turn2Id, 'message', { type: 'agentMessage', content: '第二轮的结论。' }),
      },
      requests: {},
      artifacts: {},
    },
  })
}

describe('turn conclusion separation', () => {
  it('renders a later turn as its own row and keeps the earlier conclusion as that turn answer', () => {
    const messages = selectCoreWorkbenchMessages(twoTurnSnapshot())

    expect(messages.map(message => message.id)).toEqual(['assistant:turn-1', 'assistant:turn-2'])

    const [first, second] = messages
    // The earlier conclusion stays the answer of its own turn.
    expect(first.answerText).toBe('第一轮的结论。')
    expect((first.processParts ?? []).map(part => part.id)).not.toContain('a1')
    // The later turn owns its own text; nothing is merged either way.
    expect(second.answerText).toBe('第二轮的结论。')
    expect(first.content).not.toContain('第二轮的结论')
    expect(second.content).not.toContain('第一轮的结论')
    // A concluded turn is not the live one, so it renders as complete.
    expect(first.metadata?.live).toBeFalsy()
    expect(second.metadata?.live).toBeFalsy()
  })

  it('keeps the earlier conclusion out of its collapsed process timeline', () => {
    const [first] = selectCoreWorkbenchMessages(twoTurnSnapshot())
    // Process rows may collapse; the conclusion must not be one of them.
    expect((first.processParts ?? []).map(part => part.partType)).toEqual(['reasoning'])
    expect(first.answerPart?.partType).toBe('model_text')
  })

  it('boundary: a continuation attributed to the earlier turn id would merge and demote it', () => {
    // This documents where the distinction is decided: the client splits purely
    // on the backend's turn id. If a continuation is projected under the earlier
    // turn id, the two conclusions share one message and the earlier one is
    // demoted to process. That is a projection attribution matter, not a client
    // rendering rule.
    const messages = selectCoreWorkbenchMessages(twoTurnSnapshot('turn-1'))
    expect(messages).toHaveLength(1)
    const [merged] = messages
    expect(merged.answerText).toBe('第二轮的结论。')
    expect((merged.processParts ?? []).map(part => part.id)).toContain('a1')
  })
})
