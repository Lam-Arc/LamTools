import { nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { useCoreWorkbenchProjectionController } from '../src/composables'
import type { CoreAppSnapshot } from '../src/appServer'
import type { CoreMessage } from '../src/types'

function snapshot(
  threadId: string,
  status: string,
  options: { includeTool?: boolean; includeApproval?: boolean; snapshotSeq?: number } = {},
): CoreAppSnapshot {
  const items = options.includeTool || options.includeApproval ? {
    [options.includeApproval ? 'approval-1' : 'tool-1']: {
      item_id: options.includeApproval ? 'approval-1' : 'tool-1',
      turn_id: 'turn-1',
      kind: options.includeApproval ? 'approval_request' : 'tool_call',
      status: options.includeApproval ? 'pending' : 'running',
      payload: options.includeApproval ? {
        request_id: 'request-1',
        question: 'Allow the change?',
      } : {
        tool_name: 'write_file',
      },
    },
  } : {}
  const itemOrder = Object.keys(items)
  return {
    thread_id: threadId,
    snapshot_seq: options.snapshotSeq ?? 1,
    status: status as CoreAppSnapshot['status'],
    core: {
      thread_id: threadId,
      snapshot_seq: options.snapshotSeq ?? 1,
      status: status as CoreAppSnapshot['status'],
      item_order: itemOrder,
      items,
      requests: options.includeApproval ? {
        'request-1': { request_id: 'request-1', status: 'pending', item_id: 'approval-1' },
      } : {},
      turns: {
        'turn-1': { turn_id: 'turn-1', status },
      },
    },
  }
}

function systemMessage(id: string): CoreMessage {
  return { id, role: 'system', content: id, timestamp: '' }
}

function detailedSystemMessage(metadataValue: string, partStatus: 'running' | 'completed', partContent: string): CoreMessage {
  return {
    id: 'system-1',
    role: 'system',
    content: 'same content',
    timestamp: '',
    metadata: { value: metadataValue },
    parts: [{
      id: 'system-part-1',
      partType: 'status',
      status: partStatus,
      content: partContent,
    }],
  }
}

function createController(
  state: CoreAppSnapshot | null = snapshot('thread-a', 'idle'),
  systemMessages = ref<CoreMessage[]>([]),
) {
  const activeThreadId = ref<string | null>('thread-a')
  const currentSnapshot = ref<CoreAppSnapshot | null>(state)
  const status = ref(String(state?.status || 'idle'))
  const submittingApprovalRequestIds = ref(new Set<string>())
  const shallowThinkingPending = ref(false)
  const statusChanges: string[] = []
  const finished: string[] = []
  const controller = useCoreWorkbenchProjectionController({
    snapshot: currentSnapshot,
    activeThreadId,
    status,
    submittingApprovalRequestIds,
    shallowThinkingPending,
    source: 'writer_app_server',
    systemMessages,
    onStatusChange: ({ threadId, status: nextStatus }) => statusChanges.push(`${threadId}:${nextStatus}`),
    onTurnFinished: ({ threadId, status: nextStatus }) => finished.push(`${threadId}:${nextStatus}`),
  })
  return {
    activeThreadId,
    controller,
    currentSnapshot,
    finished,
    shallowThinkingPending,
    status,
    statusChanges,
    submittingApprovalRequestIds,
    systemMessages,
  }
}

describe('useCoreWorkbenchProjectionController', () => {
  it('rebuilds projected messages for incremental snapshots', async () => {
    const fixture = createController()
    fixture.status.value = 'running'
    fixture.currentSnapshot.value = snapshot('thread-a', 'running', { includeTool: true, snapshotSeq: 2 })
    await nextTick()

    expect(fixture.controller.messages.value).toMatchObject([{
      id: 'assistant:turn-1',
      metadata: { source: 'writer_app_server' },
      parts: [{ id: 'tool-1', partType: 'tool_call', status: 'running' }],
    }])
  })

  it('projects submitting approvals as running', async () => {
    const fixture = createController()
    fixture.status.value = 'waiting'
    fixture.currentSnapshot.value = snapshot('thread-a', 'waiting', { includeApproval: true })
    fixture.submittingApprovalRequestIds.value = new Set(['request-1'])
    await nextTick()

    expect(fixture.controller.messages.value[0]?.parts?.[0]).toMatchObject({
      id: 'approval-1',
      partType: 'decision',
      status: 'running',
    })
  })

  it('automatically expands active processes while preserving manual expansion', async () => {
    const fixture = createController()
    fixture.controller.toggleProcess('manual')
    fixture.status.value = 'running'
    fixture.currentSnapshot.value = snapshot('thread-a', 'running', { includeTool: true })
    await nextTick()

    expect([...fixture.controller.processExpandedIds.value].sort()).toEqual(['assistant:turn-1', 'manual'])
  })

  it('clears projection and expansion when switching threads before a new snapshot arrives', async () => {
    const fixture = createController(snapshot('thread-a', 'running', { includeTool: true }))
    fixture.status.value = 'running'
    await nextTick()
    expect(fixture.controller.processExpandedIds.value).toEqual(new Set(['assistant:turn-1']))

    fixture.activeThreadId.value = 'thread-b'
    await nextTick()

    expect(fixture.controller.messages.value).toEqual([])
    expect(fixture.controller.processExpandedIds.value).toEqual(new Set())
  })

  it('reports a terminal transition once despite repeated terminal snapshots', async () => {
    const fixture = createController()
    fixture.status.value = 'running'
    fixture.currentSnapshot.value = snapshot('thread-a', 'running', { includeTool: true })
    await nextTick()

    fixture.status.value = 'completed'
    fixture.currentSnapshot.value = snapshot('thread-a', 'completed', { includeTool: true, snapshotSeq: 2 })
    await nextTick()
    fixture.currentSnapshot.value = snapshot('thread-a', 'completed', { includeTool: true, snapshotSeq: 3 })
    await nextTick()

    expect(fixture.finished).toEqual(['thread-a:completed'])
  })

  it('reports active thread status changes without a matching snapshot and keeps system messages', async () => {
    const fixture = createController(
      snapshot('thread-a', 'idle'),
      ref([systemMessage('system-1')]),
    )
    await nextTick()
    fixture.statusChanges.length = 0
    fixture.currentSnapshot.value = null
    await nextTick()

    fixture.status.value = 'running'
    await nextTick()
    fixture.shallowThinkingPending.value = true
    await nextTick()
    fixture.status.value = 'failed'
    await nextTick()
    fixture.currentSnapshot.value = snapshot('thread-other', 'failed')
    await nextTick()

    expect(fixture.statusChanges).toEqual(['thread-a:running', 'thread-a:failed'])
    expect(fixture.controller.messages.value).toEqual([systemMessage('system-1')])
  })

  it('refreshes projection when system messages mutate in place', async () => {
    const systemMessages = ref([systemMessage('system-1')])
    const fixture = createController(snapshot('thread-a', 'idle'), systemMessages)
    await nextTick()

    systemMessages.value.push(systemMessage('system-2'))
    await nextTick()
    expect(fixture.controller.messages.value.map((message) => message.id)).toEqual(['system-1', 'system-2'])

    systemMessages.value.splice(0, 1)
    await nextTick()
    expect(fixture.controller.messages.value.map((message) => message.id)).toEqual(['system-2'])
  })

  it('does not report finished for an initial terminal state or its replay', async () => {
    const fixture = createController(snapshot('thread-a', 'failed'))
    await nextTick()
    fixture.currentSnapshot.value = snapshot('thread-a', 'failed', { snapshotSeq: 2 })
    await nextTick()

    expect(fixture.finished).toEqual([])
  })

  it('does not finish from a cached active status before an authoritative active snapshot', async () => {
    const fixture = createController(null)
    await nextTick()
    fixture.statusChanges.length = 0
    fixture.status.value = 'running'
    await nextTick()
    fixture.status.value = 'completed'
    await nextTick()

    fixture.currentSnapshot.value = snapshot('thread-a', 'completed', { snapshotSeq: 1 })
    await nextTick()
    expect(fixture.statusChanges).toEqual(['thread-a:running', 'thread-a:completed'])
    expect(fixture.finished).toEqual([])

    fixture.status.value = 'running'
    fixture.currentSnapshot.value = snapshot('thread-a', 'running', { snapshotSeq: 2 })
    await nextTick()
    fixture.status.value = 'completed'
    fixture.currentSnapshot.value = snapshot('thread-a', 'completed', { snapshotSeq: 3 })
    await nextTick()

    expect(fixture.finished).toEqual(['thread-a:completed'])
  })

  it('refreshes replacement system messages with the same shallow signature', async () => {
    const systemMessages = ref([detailedSystemMessage('before', 'running', 'before')])
    const fixture = createController(snapshot('thread-a', 'idle'), systemMessages)
    await nextTick()

    systemMessages.value.splice(0, 1, detailedSystemMessage('after', 'completed', 'after'))
    await nextTick()

    expect(fixture.controller.messages.value).toMatchObject([{
      id: 'system-1',
      metadata: { value: 'after' },
      parts: [{ id: 'system-part-1', status: 'completed', content: 'after' }],
    }])
  })

  it('uses injected status for matching snapshots and finishes after an authoritative active snapshot', async () => {
    const fixture = createController(snapshot('thread-a', 'running', { includeTool: true }))
    await nextTick()
    fixture.shallowThinkingPending.value = true
    await nextTick()
    fixture.statusChanges.length = 0
    fixture.finished.length = 0

    fixture.status.value = 'completed'
    await nextTick()

    const assistant = fixture.controller.messages.value.find((message) => message.role === 'assistant')
    expect(assistant?.metadata?.shallowThinkingPending).toBeUndefined()
    expect(fixture.statusChanges).toEqual(['thread-a:completed'])
    expect(fixture.finished).toEqual(['thread-a:completed'])
  })
})
