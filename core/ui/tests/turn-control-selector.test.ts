import { describe, expect, it } from 'vitest'
import { selectTurnControl } from '../src/appServer/selectors.ts'
import { selectPendingInteractionDecisions } from '../src/appServer/pendingDecisions.ts'

function snapshot(partial: Record<string, unknown>) {
  return {
    thread_id: 'thread',
    snapshot_seq: 1,
    status: 'idle',
    turns: {},
    core: { status: 'idle', turns: {}, requests: {}, items: {} },
    ...partial,
  } as never
}

describe('selectTurnControl', () => {
  it('offers stop while a turn is running', () => {
    const control = selectTurnControl(snapshot({
      status: 'running',
      turns: { t1: { turn_id: 't1', status: 'running', last_seq: 2 } },
    }))
    expect(control.status).toBe('running')
    expect(control.actionMode).toBe('stop')
    expect(control.canSend).toBe(false)
  })

  it('offers resume and names the paused turn', () => {
    const control = selectTurnControl(snapshot({
      status: 'paused',
      turns: { t1: { turn_id: 't1', status: 'paused', last_seq: 2 } },
    }))
    expect(control.status).toBe('paused')
    expect(control.actionMode).toBe('resume')
    expect(control.pausedTurnId).toBe('t1')
  })

  it('offers send after a terminal turn', () => {
    const control = selectTurnControl(snapshot({
      status: 'completed',
      turns: { t1: { turn_id: 't1', status: 'completed', last_seq: 3 } },
    }))
    expect(control.actionMode).toBe('send')
    expect(control.canSend).toBe(true)
    expect(control.canTerminate).toBe(false)
  })

  it('maps interrupting to a stop affordance', () => {
    const control = selectTurnControl(snapshot({
      status: 'interrupting',
      turns: { t1: { turn_id: 't1', status: 'interrupting', last_seq: 4 } },
    }))
    expect(control.status).toBe('stopping')
    expect(control.actionMode).toBe('stop')
  })

  it('does not let a nested child row reopen a completed parent', () => {
    const control = selectTurnControl(snapshot({
      status: 'completed',
      core: {
        status: 'completed',
        turns: { t1: { turn_id: 't1', status: 'completed', last_seq: 5 } },
        requests: {},
        items: {
          child: {
            item_id: 'child',
            turn_id: 't1',
            parent_item_id: 'parent-tool',
            kind: 'approval_request',
            status: 'waiting',
          },
        },
      },
    }))
    expect(control.status).toBe('completed')
    expect(control.actionMode).toBe('send')
  })

  it('surfaces a server interaction whose card is outside the window', () => {
    const decisions = selectPendingInteractionDecisions([
      {
        interaction_id: 'interaction-1',
        turn_id: 't1',
        kind: 'question',
        status: 'open',
        title: 'Which source?',
        context: 'legacy background',
        options: [{ id: 'option-1', label: 'A' }],
      },
      { interaction_id: 'closed', kind: 'approval', status: 'answered', title: 'done' },
    ])
    expect(decisions).toHaveLength(1)
    expect(decisions[0].partId).toBe('interaction:interaction-1')
    expect(decisions[0].requestId).toBe('interaction-1')
    expect(decisions[0].isQuestion).toBe(true)
    expect(decisions[0].options[0].wireResponse).toBe('A')
    expect(decisions[0].detail).toContain('legacy background')
  })
})
