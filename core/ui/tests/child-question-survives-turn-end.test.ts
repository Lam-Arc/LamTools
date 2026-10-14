import { describe, expect, it } from 'vitest'
import { applyCoreAppEvent } from '../src/appServer/store'
import { selectPendingCoreDecisions } from '../src/appServer/pendingDecisions'
import { selectCoreWorkbenchMessages } from '../src/appServer/workbenchProjection'
import type { CoreAppEvent, CoreAppSnapshot } from '../src/appServer/protocol'

/**
 * A member's timeline outlives the parent turn that started it, so the parent
 * turn's terminal transition must leave the member's rows alone. The server
 * projection already does that (`snapshot/__init__.py`, `_close_turn_items`
 * skips `_is_sub_agent_child_item`); the live client closed them and marked a
 * child's still-waiting question as answered, so the question card vanished the
 * moment the main agent finished and the user could never answer it.
 */

const PARENT_TURN = 'thread-1:turn:turn-1'
const PARENT_CALL_ITEM = 'thread-1:thread-1:turn:turn-1:call_parent:tool'
const CHILD_QUESTION_ITEM = 'thread-1:sub:asker:run-1:inv-1:call_question:tool'
const CHILD_STATUS_ITEM = 'thread-1:sub:asker:status'
const OWN_WAITING_ITEM = 'thread-1:thread-1:turn:turn-1:call_own:tool'

function snapshot(): CoreAppSnapshot {
  return {
    thread_id: 'thread-1',
    snapshot_seq: 10,
    revision: 10,
    status: 'running',
    turns: { [PARENT_TURN]: { turn_id: PARENT_TURN, status: 'running', items: [] } },
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 10,
      revision: 10,
      status: 'running',
      seen_event_ids: [],
      turns: { [PARENT_TURN]: { turn_id: PARENT_TURN, status: 'running', items: [] } },
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
    },
  } as CoreAppSnapshot
}

function runItemEvent(
  seq: number,
  itemId: string,
  kind: string,
  status: string,
  payload: Record<string, unknown> = {},
  parentItemId = '',
): CoreAppEvent {
  // `parent_item_id` rides the envelope (that is where the client reads it),
  // while tool fields ride the nested run payload.
  return {
    method: 'core/runItem',
    seq,
    event_id: `event-${seq}`,
    item_id: itemId,
    thread_id: 'thread-1',
    turn_id: PARENT_TURN,
    created_at: new Date(0).toISOString(),
    payload: {
      item_id: itemId,
      turn_id: PARENT_TURN,
      kind,
      status,
      ...(parentItemId ? { parent_item_id: parentItemId } : {}),
      payload: { type: kind === 'status' ? 'turn' : 'serverRequest', ...payload },
    },
  }
}

function replay(events: CoreAppEvent[]): CoreAppSnapshot {
  return events.reduce((state, event) => applyCoreAppEvent(state, event) as CoreAppSnapshot, snapshot())
}

function itemStatus(state: CoreAppSnapshot, itemId: string): string | undefined {
  return state.core?.items?.[itemId]?.status
}

describe('a child question survives the parent turn ending', () => {
  it('keeps the member row waiting and the card answerable', () => {
    const state = replay([
      // The parent delegates, then the child asks its question.
      runItemEvent(1, PARENT_CALL_ITEM, 'tool_call', 'completed', {
        tool_name: 'sub_agent_message',
        // The owner attribution the panel shows comes from the call's own args.
        arguments: { type: 'execute', name: 'asker', prompt: 'ask one question' },
      }),
      runItemEvent(2, CHILD_STATUS_ITEM, 'message', 'waiting', {
        type: 'subAgentStatus',
        sub_agent: { name: 'asker', status: 'waiting' },
      }),
      runItemEvent(3, CHILD_QUESTION_ITEM, 'tool_call', 'waiting', {
        tool_name: 'question',
        request_id: 'call_question',
        sub_agent: { name: 'asker', run_id: 'run-1', invocation_id: 'inv-1', parent_item_key: 'thread-1:sub:asker' },
        arguments: { question: '哪一块优先?', options: [{ label: 'A' }, { label: 'B' }] },
      }, PARENT_CALL_ITEM),
      // The main agent finishes its turn.
      runItemEvent(4, `${PARENT_TURN}:terminal`, 'status', 'completed', { type: 'turn' }),
    ])

    expect(itemStatus(state, CHILD_QUESTION_ITEM)).toBe('waiting')
    const decisions = selectPendingCoreDecisions(selectCoreWorkbenchMessages(state))
    expect(decisions.map(decision => decision.requestId)).toEqual(['call_question'])
    expect(decisions[0].subAgentName).toBe('asker')
    expect(decisions[0].isQuestion).toBe(true)
  })

  it('still closes the parent turn own leftover request rows', () => {
    // The 2026-10-10 rule this guard must not undo: a row the parent turn owns
    // cannot stay waiting after the turn ends, or the composer stays taken over
    // by a question the runtime no longer holds.
    const state = replay([
      runItemEvent(1, OWN_WAITING_ITEM, 'tool_call', 'waiting', {
        tool_name: 'question',
        request_id: 'call_own',
        arguments: { question: '主代理自己的提问' },
      }),
      runItemEvent(2, `${PARENT_TURN}:terminal`, 'status', 'cancelled', { type: 'turn' }),
    ])

    expect(itemStatus(state, OWN_WAITING_ITEM)).toBe('cancelled')
    expect(selectPendingCoreDecisions(selectCoreWorkbenchMessages(state))).toEqual([])
  })
  it('never invents a turn from an answer row', () => {
    // The real shape of an approval_response: no member marker, and a turn id
    // derived from the answering run. Creating a turn for it left a phantom
    // `running` turn nothing closes, so the session read as running long after
    // its work had finished.
    const answeredTurn = 'thread-1:turn:child-run-1'
    const state = replay([
      runItemEvent(1, `${PARENT_TURN}:terminal`, 'status', 'completed', { type: 'turn' }),
      {
        method: 'core/runItem',
        seq: 2,
        event_id: 'event-2',
        item_id: 'call_question',
        thread_id: 'thread-1',
        turn_id: answeredTurn,
        created_at: new Date(0).toISOString(),
        payload: {
          item_id: 'call_question',
          turn_id: answeredTurn,
          kind: 'approval_response',
          status: 'completed',
          payload: { type: 'serverRequest', request_id: 'call_question', decision: 'guide', status: 'resolved' },
        },
      },
    ])

    expect(state.turns?.[answeredTurn]).toBeUndefined()
    expect(state.core?.turns?.[answeredTurn]).toBeUndefined()
    expect(state.core?.status).toBe('completed')
  })

  it('resumes the turn that owns the answered card', () => {
    const state = replay([
      runItemEvent(1, `${PARENT_TURN}:terminal`, 'status', 'waiting', { type: 'turn' }),
      {
        method: 'core/runItem',
        seq: 2,
        event_id: 'event-2',
        item_id: 'call_question',
        thread_id: 'thread-1',
        turn_id: PARENT_TURN,
        created_at: new Date(0).toISOString(),
        payload: {
          item_id: 'call_question',
          turn_id: PARENT_TURN,
          kind: 'approval_response',
          status: 'completed',
          payload: { type: 'serverRequest', request_id: 'call_question', decision: 'guide', status: 'resolved' },
        },
      },
    ])

    // The turn's own status is what the composer and the session list read.
    expect(state.core?.turns?.[PARENT_TURN]?.status).toBe('running')
  })
})
