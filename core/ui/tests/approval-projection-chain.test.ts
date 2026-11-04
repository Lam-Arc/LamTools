import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import type { CoreAppEvent, CoreAppSnapshot } from '@/appServer/protocol.ts'
import { applyCoreAppEvent } from '@/appServer/store.ts'
import { selectCoreWorkbenchMessages } from '@/appServer/workbenchProjection.ts'
import { coreDecisionSelectionPlan } from '@/appServer/workbenchActions.ts'
import { useCoreApprovalController } from '@/composables/useCoreApprovalController.ts'

/**
 * The approval chain, driven by the projection the Rust host actually emits.
 *
 * The events below are copied from `core/android-host/src-tauri/src/projection.rs`,
 * not written as the shape the UI would like to receive. That distinction is the
 * point: an earlier fix passed a hand-built object with every field present and
 * proved nothing, because the real projection did not produce those fields.
 */

const THREAD = 'th'

function runItem(
  seq: number,
  kind: string,
  itemId: string,
  body: Record<string, unknown>,
  status = 'waiting',
): CoreAppEvent {
  return {
    event_id: `${THREAD}:${seq}`,
    thread_id: THREAD,
    seq,
    method: 'core/runItem',
    created_at: '',
    payload: {
      kind,
      thread_id: THREAD,
      event_id: `${THREAD}:${seq}`,
      seq,
      turn_id: 'turn-1',
      item_id: itemId,
      status,
      payload: body,
      created_at_ms: 0,
    },
  } as unknown as CoreAppEvent
}

function emptySnapshot(): CoreAppSnapshot {
  return {
    thread_id: THREAD,
    snapshot_seq: 0,
    revision: 0,
    status: 'running',
    turns: {},
    items: {},
    item_order: [],
    requests: {},
    artifacts: {},
    seen_event_ids: [],
  } as CoreAppSnapshot
}

/** What `projection.rs` emits for an approval request, field for field. */
function approvalEvent(seq: number, callId: string, requestId: string): CoreAppEvent {
  return runItem(seq, 'approval_request', `${THREAD}:turn-1:${callId}:tool`, {
    type: 'serverRequest',
    request_id: requestId,
    tool_call_id: callId,
    kind: 'approval',
    message: '等待确认：write_file',
    tool_name: 'write_file',
    tool_args: { path: 'notes.md' },
    options: [
      { id: 'approve', label: '批准执行', description: '允许执行', response: 'approve' },
      { id: 'deny', label: '拒绝执行', description: '不执行', response: 'deny' },
    ],
    metadata: {
      request_id: requestId,
      tool_call_id: callId,
      waitingRequest: { request_id: requestId, kind: 'approval' },
    },
  })
}

function decisionParts(snapshot: CoreAppSnapshot) {
  const messages = selectCoreWorkbenchMessages(snapshot)
  const parts = messages.flatMap((message) => message.parts ?? [])
  return { messages, parts }
}

describe('approval projection chain', () => {
  it('keeps the request id from the projected event all the way to the click plan', () => {
    let snapshot = emptySnapshot()
    snapshot = applyCoreAppEvent(
      snapshot,
      runItem(5, 'tool_call', `${THREAD}:turn-1:call1:tool`, {
        type: 'dynamicToolCall',
        tool_call_id: 'call1',
        tool_name: 'write_file',
        tool_args: { path: 'notes.md' },
      }),
    )
    snapshot = applyCoreAppEvent(snapshot, approvalEvent(6, 'call1', 'appr-1'))

    const { parts } = decisionParts(snapshot)
    const decision = parts.find((part) => part.partType === 'decision')
    expect(decision, `no decision part among ${parts.map((p) => p.partType).join(',')}`).toBeTruthy()

    const plan = coreDecisionSelectionPlan(decision, {
      partId: decision!.id,
      option: { id: 'approve' },
      response: 'approve',
    } as never)

    // The failure this test exists for: a plan that degrades to plain text is a
    // click that never becomes `approval/respond`.
    expect(plan.status).toBe('approval')
    expect(plan).toMatchObject({ requestId: 'appr-1', decision: 'approve_once' })
  })
})

describe('approval controller', () => {
  /** A snapshot whose only content is one projected approval request. */
  function snapshotWithApproval(requestId = 'appr-1') {
    let snapshot = emptySnapshot()
    snapshot = applyCoreAppEvent(
      snapshot,
      runItem(5, 'tool_call', `${THREAD}:turn-1:call1:tool`, {
        type: 'dynamicToolCall',
        tool_call_id: 'call1',
        tool_name: 'write_file',
        tool_args: { path: 'notes.md' },
      }),
    )
    return applyCoreAppEvent(snapshot, approvalEvent(6, 'call1', requestId))
  }

  /**
   * The whole decision path with the real projection as input.
   *
   * This is the test that would have caught the shipped bug: the card rendered,
   * the button existed, and the click became a chat message because the request
   * id never reached the part.
   */
  it('sends approval/respond with the projected request id when approve is pressed', async () => {
    const snapshot = snapshotWithApproval('appr-live-1')
    const messages = selectCoreWorkbenchMessages(snapshot)
    const decision = messages
      .flatMap((message) => message.parts ?? [])
      .find((part) => part.partType === 'decision')
    expect(decision, 'the projection produced no decision part').toBeTruthy()

    const sent: Array<{ requestId: string; decision: string }> = []
    const controller = useCoreApprovalController({
      messages: ref(messages),
      hasActiveThread: ref(true),
      canRespondApproval: ref(true),
      respondApproval: async (requestId, decision) => {
        sent.push({ requestId, decision })
      },
      submitText: async () => {
        throw new Error('an approval must never be sent as chat text')
      },
      deferText: () => {
        throw new Error('an approval must never be deferred as text')
      },
    })

    const result = await controller.handleDecision({
      partId: decision!.id,
      option: { id: 'approve' },
      response: 'approve',
    } as never)

    expect(result).toBe('approval')
    expect(sent).toEqual([{ requestId: 'appr-live-1', decision: 'approve_once' }])
  })

  /**
   * A card that cannot be answered must say so. Silently showing "submitted" was
   * the behaviour that made a broken chain look like a slow one.
   */
  it('reports a missing approval channel instead of pretending to submit', async () => {
    const snapshot = snapshotWithApproval()
    const messages = selectCoreWorkbenchMessages(snapshot)
    const decision = messages
      .flatMap((message) => message.parts ?? [])
      .find((part) => part.partType === 'decision')

    const controller = useCoreApprovalController({
      messages: ref(messages),
      hasActiveThread: ref(true),
      canRespondApproval: ref(false),
      respondApproval: async () => {
        throw new Error('must not be called')
      },
      submitText: async () => undefined,
      deferText: () => undefined,
    })

    const result = await controller.handleDecision({
      partId: decision!.id,
      option: { id: 'approve' },
      response: 'approve',
    } as never)

    expect(result).toBe('deferred')
    expect(controller.lastError.value).toContain('unavailable')
  })
})
