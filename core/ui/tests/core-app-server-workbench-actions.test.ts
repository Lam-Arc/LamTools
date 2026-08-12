import { describe, expect, it } from 'vitest'
import {
  coreAppServerDecision,
  coreDecisionSelectionPlan,
  coreComposerSubmissionEffects,
  coreComposerActionMode,
  isCoreGuidableTurnStatus,
  normalizeCoreCommandCatalogItem,
  submitCoreComposerTask,
  type CoreCommandCatalogItem,
  type CoreInputItem,
  type MessagePart,
} from '../src'

describe('core appServer workbench actions', () => {
  const commands: CoreCommandCatalogItem[] = [
    {
      name: 'compact',
      title: 'Compact',
      description: '',
      icon: '/',
      source: 'core',
      action: 'run_action',
    },
    {
      name: 'reviewer',
      title: 'Reviewer',
      description: '',
      icon: '/',
      source: 'member',
      action: 'insert_token',
    },
  ]

  it('chooses stop only for active empty composer submissions', () => {
    expect(coreComposerActionMode({ status: 'running', text: '', pendingAttachmentCount: 0 })).toBe('stop')
    expect(coreComposerActionMode({ status: 'waiting', text: 'continue', pendingAttachmentCount: 0 })).toBe('send')
    expect(coreComposerActionMode({ status: 'running', text: '', pendingAttachmentCount: 1 })).toBe('send')
    expect(coreComposerActionMode({ status: 'idle', text: '', pendingAttachmentCount: 0 })).toBe('send')
  })

  it('allows queue guidance only while a turn can still accept steer input', () => {
    expect(isCoreGuidableTurnStatus('running')).toBe(true)
    expect(isCoreGuidableTurnStatus('waiting')).toBe(true)
    expect(isCoreGuidableTurnStatus('interrupting')).toBe(false)
    expect(isCoreGuidableTurnStatus('completed')).toBe(false)
  })

  it('normalizes command catalog items and approval decisions', () => {
    expect(normalizeCoreCommandCatalogItem({ name: '/compact', title: '', source: 'member', action: 'unknown' })).toEqual({
      name: 'compact',
      title: 'compact',
      description: '',
      icon: '/',
      source: 'member',
      action: 'run_action',
      accepts_args: false,
    })
    expect(normalizeCoreCommandCatalogItem({ name: '' })).toBeNull()
    expect(coreAppServerDecision('accept')).toBe('approve_once')
    expect(coreAppServerDecision('approve_for_session')).toBe('approve_for_session')
    expect(coreAppServerDecision('cancel')).toBe('deny')
    expect(coreAppServerDecision('use a safer path')).toBe('other_guidance')
  })

  it('plans approval responses from decision selection payloads', () => {
    const part: MessagePart = {
      id: 'part-1',
      partType: 'decision',
      status: 'pending',
      content: 'Need approval',
      metadata: {
        waitingRequest: {
          request_id: 'request-1',
        },
      },
    }

    expect(coreDecisionSelectionPlan(part, {
      partId: 'part-1',
      option: { id: 'accept', label: 'Approve' },
      response: '允许本次执行',
    })).toEqual({
      status: 'approval',
      requestId: 'request-1',
      decision: 'approve_once',
      guidance: '允许本次执行',
    })
    expect(coreDecisionSelectionPlan(null, {
      partId: 'part-2',
      option: { id: 'other', label: 'Other' },
      response: '改用只读方案',
    })).toEqual({
      status: 'text',
      text: '改用只读方案',
    })
    expect(coreDecisionSelectionPlan(null, {
      partId: 'part-3',
      option: { id: 'other', label: 'Other' },
      response: ' ',
    })).toEqual({ status: 'ignored' })
  })

  it('plans composer effects after commands, queueing, and turn starts', () => {
    expect(coreComposerSubmissionEffects(
      { status: 'command', command: 'compact', ok: true },
      { clearComposer: true, submittedText: '/compact' },
    )).toEqual({
      clearComposer: true,
      clearComposerText: '/compact',
      clearAttachments: false,
    })
    expect(coreComposerSubmissionEffects(
      { status: 'command', command: 'compact', ok: false },
      { clearComposer: true, submittedText: '/compact' },
    )).toEqual({
      clearComposer: false,
      clearAttachments: false,
      restoreText: '/compact',
    })
    expect(coreComposerSubmissionEffects(
      { status: 'queued', inputItems: [{ type: 'text', text: 'follow up' }] },
      { clearComposer: true, submittedText: 'follow up', queuedStatusText: '已加入待发送' },
    )).toEqual({
      clearComposer: true,
      clearComposerText: 'follow up',
      clearAttachments: false,
      statusText: '已加入待发送',
    })
    expect(coreComposerSubmissionEffects(
      { status: 'guided', inputItems: [{ type: 'text', text: 'change course' }] },
      { clearComposer: true, submittedText: 'change course', guidedStatusText: '引导已发送' },
    )).toEqual({
      clearComposer: true,
      clearComposerText: 'change course',
      clearAttachments: false,
      statusText: '引导已发送',
    })
    expect(coreComposerSubmissionEffects(
      { status: 'started', inputItems: [{ type: 'text', text: 'write' }], ok: true },
      { clearComposer: true, submittedText: 'write' },
    )).toEqual({
      clearComposer: true,
      clearComposerText: 'write',
      clearAttachments: true,
    })
    expect(coreComposerSubmissionEffects(
      { status: 'started', inputItems: [{ type: 'text', text: 'write' }], ok: false },
      { clearComposer: true, submittedText: 'write' },
    )).toEqual({
      clearComposer: false,
      clearAttachments: false,
      restoreText: 'write',
    })
  })

  it('executes standalone commands instead of starting a model turn', async () => {
    const calls: string[] = []

    const result = await submitCoreComposerTask({
      threadId: 'thread-1',
      text: '/compact',
      status: 'idle',
      commandCatalog: commands,
      executeCommand: async (command) => {
        calls.push(command)
        return true
      },
      queueInput: async () => {
        throw new Error('queue should not run')
      },
      startTurn: async () => {
        throw new Error('turn should not start')
      },
    })

    expect(result).toEqual({ status: 'command', command: 'compact', ok: true })
    expect(calls).toEqual(['compact'])
  })

  it('steers text while a turn is active, queues attachments, and starts turns while idle', async () => {
    const queued: CoreInputItem[][] = []
    const guided: CoreInputItem[][] = []
    const started: CoreInputItem[][] = []

    await submitCoreComposerTask({
      threadId: 'thread-1',
      activeTurnId: 'turn-1',
      text: '请 /reviewer 看看',
      status: 'running',
      forceGuide: true,
      commandCatalog: commands,
      steerTurn: async (_threadId, _turnId, inputItems) => {
        guided.push(inputItems)
      },
      queueInput: async (_threadId, inputItems) => {
        queued.push(inputItems)
      },
      startTurn: async () => false,
    })
    await submitCoreComposerTask({
      threadId: 'thread-1',
      activeTurnId: 'turn-1',
      text: '附加证据',
      status: 'running',
      attachments: [{ type: 'attachment', attachment_id: 'att-active', filename: 'active.md' }],
      queueInput: async (_threadId, inputItems) => {
        queued.push(inputItems)
      },
      steerTurn: async () => {
        throw new Error('attachments should be queued')
      },
      startTurn: async () => false,
    })
    const startedResult = await submitCoreComposerTask({
      threadId: 'thread-1',
      text: '写文档',
      status: 'idle',
      commandCatalog: commands,
      attachments: [{ type: 'attachment', attachment_id: 'att-1', filename: 'note.md' }],
      queueInput: async () => {
        throw new Error('queue should not run')
      },
      startTurn: async (_threadId, inputItems) => {
        started.push(inputItems)
        return true
      },
    })

    expect(guided).toEqual([[
      { type: 'text', text: '请 ' },
      { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
      { type: 'text', text: ' 看看' },
    ]])
    expect(queued).toEqual([[
      { type: 'text', text: '附加证据' },
      { type: 'attachment', attachment_id: 'att-active', filename: 'active.md' },
    ]])
    expect(startedResult.status).toBe('started')
    expect(started).toEqual([[
      { type: 'text', text: '写文档' },
      { type: 'attachment', attachment_id: 'att-1', filename: 'note.md' },
    ]])
  })
})
