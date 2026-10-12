/**
 * A terminal turn owns its items — on the live event path too.
 *
 * The server snapshot projection closes a terminal turn's non-terminal items
 * (`snapshot/__init__.py` `_close_turn_items`) and forces an item that lands on
 * an already-terminal turn to that terminal status. The client's event reducer
 * used to do neither, so a `question` / approval request item left `waiting` by
 * a Stop stayed `pending` in the projection: the composer stayed taken over by
 * a question the runtime no longer held, and every option click answered
 * "no pending approval". Reloading cleared it (the server snapshot was right),
 * which is what the user saw on 2026-10-10.
 */
import { describe, expect, it } from 'vitest'
import {
  applyCoreAppEvent,
  hydrateSnapshot,
  selectCoreWorkbenchMessages,
  selectPendingCoreDecisions,
  type CoreAppEvent,
  type CoreAppSnapshot,
} from '../src/appServer'

const TURN_ID = 'turn-1'
const REQUEST_ITEM_ID = 'turn-1:question'

const QUESTION_OPTIONS = [
  { id: 'a', label: '方案 A', response: '方案 A' },
  { id: 'b', label: '方案 B', response: '方案 B' },
]

/** Projection-shaped snapshot whose turn is parked on a model question. */
function waitingSnapshot(): CoreAppSnapshot {
  return hydrateSnapshot({
    thread_id: 'thread-1',
    snapshot_seq: 20,
    status: 'waiting',
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 20,
      status: 'waiting',
      item_order: [REQUEST_ITEM_ID],
      turns: {
        [TURN_ID]: { turn_id: TURN_ID, status: 'waiting', items: [REQUEST_ITEM_ID] },
      },
      items: {
        [REQUEST_ITEM_ID]: {
          item_id: REQUEST_ITEM_ID,
          turn_id: TURN_ID,
          kind: 'approval_request',
          status: 'waiting',
          payload: {
            type: 'serverRequest',
            request_id: 'req-1',
            tool_name: 'question',
            message: '这次要按哪个方案改？',
            options: QUESTION_OPTIONS,
          },
        },
      },
      requests: {
        'req-1': { request_id: 'req-1', status: 'open', item_id: REQUEST_ITEM_ID, turn_id: TURN_ID },
      },
    },
  } satisfies CoreAppSnapshot)
}

/** The same thread after Stop landed: turn already terminal, no request item. */
function cancelledSnapshot(): CoreAppSnapshot {
  return hydrateSnapshot({
    thread_id: 'thread-1',
    snapshot_seq: 21,
    status: 'cancelled',
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 21,
      status: 'cancelled',
      item_order: [],
      turns: {
        [TURN_ID]: { turn_id: TURN_ID, status: 'cancelled', items: [] },
      },
      items: {},
      requests: {},
    },
  } satisfies CoreAppSnapshot)
}

function statusEvent(eventId: string, status: string): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq: 30,
    method: 'core/runItem',
    created_at: '2026-10-10T00:00:00Z',
    turn_id: TURN_ID,
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      turn_id: TURN_ID,
      kind: 'status',
      status,
      payload: { type: 'turn', status },
    },
  }
}

function approvalRequestEvent(eventId: string, status: string): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq: 31,
    method: 'core/runItem',
    created_at: '2026-10-10T00:00:01Z',
    item_id: REQUEST_ITEM_ID,
    turn_id: TURN_ID,
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      item_id: REQUEST_ITEM_ID,
      turn_id: TURN_ID,
      kind: 'approval_request',
      status,
      payload: {
        type: 'serverRequest',
        request_id: 'req-1',
        tool_name: 'question',
        message: '这次要按哪个方案改？',
        options: QUESTION_OPTIONS,
      },
    },
  }
}

/** What the composer sees: the decisions still waiting to be answered. */
function pendingDecisions(snapshot: CoreAppSnapshot) {
  const messages = selectCoreWorkbenchMessages(snapshot, { source: 'core_app_server' })
  return selectPendingCoreDecisions(messages)
}

describe('live projection: a terminal turn owns its items', () => {
  it('releases the question card when Stop closes the turn', () => {
    let snapshot = waitingSnapshot()
    // Baseline: the question owns the input area while the turn is parked.
    expect(pendingDecisions(snapshot)).toHaveLength(1)

    snapshot = applyCoreAppEvent(snapshot, statusEvent('stop-1', 'interrupting'))
    // Interrupting is not terminal: the card stays until the turn really ends.
    expect(pendingDecisions(snapshot)).toHaveLength(1)

    snapshot = applyCoreAppEvent(snapshot, statusEvent('stop-2', 'cancelled'))
    expect(snapshot.core?.items?.[REQUEST_ITEM_ID]?.status).toBe('cancelled')
    expect(snapshot.core?.turns?.[TURN_ID]?.status).toBe('cancelled')
    expect(pendingDecisions(snapshot)).toEqual([])
  })

  it('does not let a question arriving after Stop take the composer over', () => {
    // The race the user hit: the model asks at the same moment Stop lands, and
    // the request event reaches the client after the turn is already terminal.
    const snapshot = applyCoreAppEvent(cancelledSnapshot(), approvalRequestEvent('late-1', 'waiting'))

    expect(snapshot.core?.items?.[REQUEST_ITEM_ID]?.status).toBe('cancelled')
    // A late event must not revive the turn either.
    expect(snapshot.core?.status).toBe('cancelled')
    expect(snapshot.core?.turns?.[TURN_ID]?.status).toBe('cancelled')
    expect(pendingDecisions(snapshot)).toEqual([])
  })

  it('ignores a parked-turn status event that lands after the turn is closed', () => {
    // The parked loop emits `runtime.waiting` alongside the request; if it is
    // delivered after Stop, the composer must not go back to "turn active".
    const cancelled = applyCoreAppEvent(cancelledSnapshot(), statusEvent('park-1', 'waiting'))

    expect(cancelled.core?.turns?.[TURN_ID]?.status).toBe('cancelled')
    expect(cancelled.core?.status).toBe('cancelled')
    expect(pendingDecisions(cancelled)).toEqual([])
  })

  it('keeps a question on a live turn actionable', () => {
    const running = hydrateSnapshot({
      ...waitingSnapshot(),
      status: 'running',
      core: { ...waitingSnapshot().core!, status: 'running' },
    } satisfies CoreAppSnapshot)
    const snapshot = applyCoreAppEvent(running, approvalRequestEvent('ask-1', 'waiting'))

    expect(snapshot.core?.items?.[REQUEST_ITEM_ID]?.status).toBe('waiting')
    expect(snapshot.core?.status).toBe('waiting')
    expect(pendingDecisions(snapshot)).toHaveLength(1)
  })
})
