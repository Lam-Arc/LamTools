import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useCoreLiveComposerController } from '../src/composables/useCoreLiveComposerController'
import { CoreHistoryEditConflictError, CoreRequestAcceptanceUnknownError } from '../src/appServer/client'
import type { UseCoreLiveComposerControllerOptions } from '../src/composables/useCoreLiveComposerController'
import type { CoreInputItem } from '../src/types'

// user:“做吧”+(先证明异步发送固定参数、保护草稿，并让每条消息独立恢复)。
function deferred<T = void>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

function setup(overrides: Partial<UseCoreLiveComposerControllerOptions> = {}) {
  const thread = ref<string | null>('a')
  const text = ref('original')
  const attachments = ref<CoreInputItem[]>([{ type: 'attachment', attachment_id: 'file-a', filename: 'a.txt' }])
  const status = ref('idle')
  const turn = ref('turn-a')
  const startTurn = vi.fn<UseCoreLiveComposerControllerOptions['startTurn']>(async () => {})
  const clearComposer = vi.fn(() => { text.value = '' })
  const clearAttachments = vi.fn((submitted: CoreInputItem[] = attachments.value) => {
    attachments.value = attachments.value.filter(item => !submitted.some(sent => JSON.stringify(sent) === JSON.stringify(item)))
  })
  const controller = useCoreLiveComposerController({
    activeThreadId: thread, activeTurnId: turn, connectedThreadId: thread as never,
    connectionState: ref('open'), text, cursor: ref(0), status, attachments,
    connect: async () => {}, startTurn, interruptTurn: async () => {}, pauseTurn: async () => {},
    forceResetTurn: async () => {}, queueInput: async () => {}, listCommands: async () => [],
    getWorkRoot: () => 'E:/A', executeCommand: async () => true,
    clearComposer, clearAttachments, ...overrides,
  })
  return { controller, thread, text, attachments, status, turn, startTurn, clearComposer, clearAttachments }
}

describe('submission lifecycle acceptance', () => {
  it('requires reopening an edit after a version conflict', async () => {
    const startTurn = vi.fn<UseCoreLiveComposerControllerOptions['startTurn']>(async () => {
      if (startTurn.mock.calls.length === 1) throw new CoreHistoryEditConflictError()
    })
    const s = setup({ startTurn })
    const message = { threadId: 'a', turnId: 'old', expectedRevision: 12, text: 'revised', attachments: [] }
    await s.controller.replaceMessage(message)
    const conflict = s.controller.submissions.value[0]
    expect(conflict).toMatchObject({ needsReopen: true })
    await s.controller.retrySubmission(conflict.id)
    expect(startTurn).toHaveBeenCalledTimes(1)
    await s.controller.replaceMessage({ ...message, expectedRevision: 14 })
    expect(startTurn.mock.calls[1][3]).toMatchObject({ expected_revision: 14 })
  })
  // user:“全做”+(历史编辑固定会话和回合，即使正在切换或服务器忙也不能改走普通发送)。
  it('binds a historical edit to its source across session switches and refuses busy fallback', async () => {
    const gate = deferred<Record<string, unknown>>()
    const queueInput = vi.fn(async () => {})
    const startTurn = vi.fn<UseCoreLiveComposerControllerOptions['startTurn']>(async () => {
      throw Object.assign(new Error('session has an active turn'), { code: 'SESSION_BUSY' })
    })
    const s = setup({ turnOptions: () => gate.promise, queueInput, startTurn })
    const edit = s.controller.replaceMessage({ threadId: 'a', turnId: 'old-turn', expectedRevision: 12, text: '/literal', attachments: [] })
    s.thread.value = 'b'
    s.text.value = 'draft B'
    gate.resolve({ model_id: 'model-a' })
    await edit
    expect(startTurn).toHaveBeenCalledWith('a', [{ type: 'text', text: '/literal' }], 'E:/A', {
      model_id: 'model-a', replace_turn_id: 'old-turn', expected_revision: 12,
    }, expect.any(String))
    expect(queueInput).not.toHaveBeenCalled()
    expect(s.text.value).toBe('draft B')
    expect(s.controller.submissions.value[0]).toMatchObject({ threadId: 'a', state: 'failed', replaceTurnId: 'old-turn' })
  })

  it('does not clear composer attachments when accepted external input has the same id', async () => {
    const s = setup()
    await s.controller.submit({ text: 'external', attachments: [...s.attachments.value] })
    expect(s.attachments.value).toHaveLength(1)
    expect(s.clearAttachments).not.toHaveBeenCalled()
  })

  it('shows preparation immediately and captures attachments, target and status before async options', async () => {
    const gate = deferred<Record<string, unknown>>()
    const s = setup({ turnOptions: () => gate.promise })
    const sending = s.controller.submit({ clearComposer: true })
    expect(s.controller.submissions.value[0]).toMatchObject({ threadId: 'a', text: 'original', state: 'preparing' })
    s.thread.value = 'b'; s.turn.value = 'turn-b'; s.status.value = 'running'
    s.attachments.value = [{ type: 'attachment', attachment_id: 'file-b' }]
    s.text.value = 'draft in B'
    gate.resolve({ model_id: 'model-a' })
    await sending
    expect(s.startTurn).toHaveBeenCalledWith('a', expect.arrayContaining([{ type: 'attachment', attachment_id: 'file-a', filename: 'a.txt' }]), 'E:/A', { model_id: 'model-a' }, expect.any(String))
    expect(s.text.value).toBe('draft in B')
    expect(s.attachments.value[0]).toMatchObject({ attachment_id: 'file-b' })
  })

  it.each(['success', 'failure'] as const)('preserves a newer draft and attachment after %s', async outcome => {
    const gate = deferred()
    const s = setup({ startTurn: async () => { await gate.promise; if (outcome === 'failure') throw new Error('rejected') } })
    const sending = s.controller.submit({ clearComposer: true })
    await nextTick()
    s.text.value = 'new draft'
    s.attachments.value = [{ type: 'attachment', attachment_id: 'new-file' }]
    gate.resolve()
    await sending
    expect(s.text.value).toBe('new draft')
    expect(s.attachments.value).toEqual([{ type: 'attachment', attachment_id: 'new-file' }])
    if (outcome === 'failure') {
      expect(s.controller.submissions.value[0]).toMatchObject({ state: 'failed', error: 'rejected' })
      expect(s.controller.lastError.value).toBe('rejected')
    }
  })

  it('clears only submitted attachments after queue acceptance', async () => {
    const gate = deferred()
    const s = setup({ queueInput: async () => { await gate.promise } })
    s.status.value = 'running'
    const sending = s.controller.submit({ clearComposer: true })
    await nextTick()
    s.attachments.value = [...s.attachments.value, { type: 'attachment', attachment_id: 'new-file' }]
    gate.resolve(); await sending
    expect(s.attachments.value).toEqual([{ type: 'attachment', attachment_id: 'new-file' }])
    expect(s.controller.submissions.value[0].state).toBe('queued')
  })

  it('retries an uncertain submission with its original identity, body and options', async () => {
    const calls: unknown[][] = []
    const turnOptions = vi.fn(() => ({ model_id: 'original-model' }))
    const s = setup({ turnOptions, startTurn: async (...args) => {
      calls.push(args)
      if (calls.length === 1) throw new CoreRequestAcceptanceUnknownError(args[4]!, new Error('lost reply'))
    } })
    await s.controller.submit({ clearComposer: true })
    const record = s.controller.submissions.value[0]
    expect(record.state).toBe('unknown')
    s.text.value = 'next draft'; s.status.value = 'running'
    await s.controller.retrySubmission(record.id)
    expect(calls[1]).toEqual(calls[0])
    expect(turnOptions).toHaveBeenCalledTimes(1)
    expect(s.text.value).toBe('next draft')
  })

  it('never resubmits a parent supplement when member recovery fails', async () => {
    const resumeTurn = vi.fn(async () => {})
    const resumeSubAgents = vi.fn(async () => { throw new Error('member unavailable') })
    const s = setup({ resumableTurnId: ref('paused'), resumableSubAgents: ref(['child']), resumeTurn, resumeSubAgents })
    await s.controller.submit({ clearComposer: true })
    expect(s.text.value).toBe('')
    expect(s.attachments.value).toEqual([])
    const record = s.controller.submissions.value[0]
    expect(record.state).toBe('failed')
    await s.controller.retrySubmission(record.id)
    expect(resumeTurn).toHaveBeenCalledTimes(1)
    expect(resumeSubAgents).toHaveBeenCalledTimes(2)
    s.controller.acknowledgeSubmission('a', record.id)
    expect(s.controller.submissions.value[0].state).toBe('failed')
  })

  it('does not let an unrelated receipt retire an uncertain message', async () => {
    const s = setup({ startTurn: async (_thread, _input, _root, _options, id) => {
      throw new CoreRequestAcceptanceUnknownError(id!, new Error('lost'))
    } })
    await s.controller.submit()
    const id = s.controller.submissions.value[0].id
    s.controller.acknowledgeSubmission('b', id)
    s.controller.acknowledgeSubmission('a', 'other')
    expect(s.controller.submissions.value[0].state).toBe('unknown')
    s.controller.acknowledgeSubmission('a', id)
    expect(s.controller.submissions.value[0].state).toBe('accepted')
  })

  it('preserves the snapshot turn and identity when retrying guidance after a lost receipt', async () => {
    const calls: unknown[][] = []
    const s = setup({ steerTurn: async (...args) => {
      calls.push(args)
      if (calls.length === 1) throw new CoreRequestAcceptanceUnknownError(args[3]!, new Error('lost'))
      return true
    } })
    s.status.value = 'running'
    // 默认「直接引导」模式下运行中的普通发送键就是引导（旧 forceGuide 标记已移除）。
    await s.controller.submit({ clearComposer: true })
    const id = s.controller.submissions.value[0].id
    s.turn.value = 'different-turn'
    await s.controller.retrySubmission(id)
    expect(calls[1]).toEqual(calls[0])
    expect(calls[0][1]).toBe('turn-a')
    expect(calls[0][3]).toBe(id)
  })

  it('does not switch the subscription back to the old chat when preparation finishes late', async () => {
    const gate = deferred<Record<string, unknown>>()
    const connect = vi.fn(async () => {})
    const connectedThreadId = ref('a')
    const s = setup({ connect, connectedThreadId, turnOptions: () => gate.promise })
    const sending = s.controller.submit()
    s.thread.value = 'b'; connectedThreadId.value = 'b'
    gate.resolve({})
    await sending
    expect(connect).not.toHaveBeenCalled()
    expect(s.startTurn.mock.calls[0][0]).toBe('a')
  })

  it('keeps late action-command failure out of another chat draft', async () => {
    const gate = deferred()
    const s = setup({ attachments: ref([]), executeCommand: async () => { await gate.promise; throw new Error('command failed') } })
    s.text.value = '/test'
    const running = s.controller.runCommand('test')
    await nextTick()
    s.thread.value = 'b'; s.text.value = ''
    gate.resolve(); await running
    expect(s.text.value).toBe('')
  })

  it('continues an empty paused turn without manufacturing an empty user message', async () => {
    const resumeTurn = vi.fn(async () => {})
    const s = setup({ resumableTurnId: ref('paused'), attachments: ref([]), resumeTurn })
    s.text.value = ''
    await s.controller.submit()
    expect(resumeTurn).toHaveBeenCalledWith('a', 'paused', [], expect.any(String))
  })

  it('uses the same host validation for direct send and keyboard send', async () => {
    const canSubmit = vi.fn(() => false)
    const s = setup({ canSubmit })
    await s.controller.submit()
    await s.controller.handleKeydown(new KeyboardEvent('keydown', { key: 'Enter' }))
    expect(canSubmit).toHaveBeenCalledTimes(2)
    expect(s.startTurn).not.toHaveBeenCalled()
    expect(s.text.value).toBe('original')
  })

  // user:“修吧 让用户更易用”+(服务端说会话仍处于暂停时，发送应继续那个暂停回合，
  // 而不是把“有会话处于暂停”当失败丢回给用户)。
  it('continues the paused turn when a start is refused as paused', async () => {
    const resumeTurn = vi.fn(async () => {})
    const startTurn = vi.fn<UseCoreLiveComposerControllerOptions['startTurn']>(async () => {
      throw Object.assign(new Error('session has a paused turn'), {
        code: 'INVALID_REQUEST',
        data: { code: 'SESSION_PAUSED', reason: 'paused_turn_exists', paused_turn_id: 'turn-paused' },
      })
    })
    const s = setup({ startTurn, resumeTurn })
    await s.controller.submit({ clearComposer: true })

    expect(startTurn).toHaveBeenCalledTimes(1)
    expect(resumeTurn).toHaveBeenCalledWith('a', 'turn-paused', [
      { type: 'text', text: 'original' },
      { type: 'attachment', attachment_id: 'file-a', filename: 'a.txt' },
    ], expect.any(String))
    expect(s.controller.lastError.value).toBe('')
    expect(s.controller.submissions.value[0]?.state).toBe('accepted')
    expect(s.text.value).toBe('')
    expect(s.attachments.value).toEqual([])
  })

  it('queues the text when the paused turn can no longer be continued', async () => {
    const queueInput = vi.fn(async (_threadId: string, _inputItems: unknown[], _options?: unknown, _id?: string) => {})
    const startTurn = vi.fn<UseCoreLiveComposerControllerOptions['startTurn']>(async () => {
      throw Object.assign(new Error('session has a paused turn'), {
        code: 'INVALID_REQUEST',
        data: { code: 'SESSION_PAUSED', reason: 'paused_turn_exists', paused_turn_id: 'turn-gone' },
      })
    })
    const resumeTurn = vi.fn(async () => {
      throw new Error('latest turn is not resumable')
    })
    const s = setup({ startTurn, resumeTurn, queueInput })
    await s.controller.submit({ clearComposer: true })

    // 继续失败也不能把这条消息弄丢：落到队列，按“已排队”收尾。
    expect(queueInput).toHaveBeenCalledTimes(1)
    expect(queueInput.mock.calls[0]?.[0]).toBe('a')
    expect(JSON.stringify(queueInput.mock.calls[0]?.[1])).toContain('original')
    expect(s.controller.submissions.value[0]?.state).toBe('queued')
    expect(s.controller.lastError.value).toBe('')
  })

  it('continues the latest paused turn when the refusal carries no turn id', async () => {
    const resumeTurn = vi.fn(async () => {})
    const startTurn = vi.fn<UseCoreLiveComposerControllerOptions['startTurn']>(async () => {
      // 旧服务端只给文字，没有 paused_turn_id；空 id 表示“继续最近暂停的一轮”。
      throw Object.assign(new Error('session has a paused turn'), { code: 'INVALID_REQUEST' })
    })
    const s = setup({ startTurn, resumeTurn })
    await s.controller.submit({ clearComposer: true })

    expect(resumeTurn).toHaveBeenCalledWith('a', '', expect.any(Array), expect.any(String))
    expect(s.controller.submissions.value[0]?.state).toBe('accepted')
  })

  it('never turns a historical edit into a pause continuation', async () => {
    const resumeTurn = vi.fn(async () => {})
    const queueInput = vi.fn(async () => {})
    const startTurn = vi.fn<UseCoreLiveComposerControllerOptions['startTurn']>(async () => {
      throw Object.assign(new Error('session has a paused turn'), {
        code: 'INVALID_REQUEST',
        data: { code: 'SESSION_PAUSED', reason: 'paused_turn_exists', paused_turn_id: 'turn-paused' },
      })
    })
    const s = setup({ startTurn, resumeTurn, queueInput, turnOptions: () => ({}) })
    await s.controller.replaceMessage({
      threadId: 'a', turnId: 'old-turn', expectedRevision: 3, text: '修正', attachments: [],
    })

    expect(resumeTurn).not.toHaveBeenCalled()
    expect(queueInput).not.toHaveBeenCalled()
    expect(s.controller.submissions.value[0]).toMatchObject({ state: 'failed', replaceTurnId: 'old-turn' })
  })

  it('allows Stop after acceptance even while the original send reply is pending', async () => {
    const gate = deferred()
    const pauseTurn = vi.fn(async () => {})
    const s = setup({ attachments: ref([]), startTurn: async () => { await gate.promise }, pauseTurn })
    const sending = s.controller.submit({ clearComposer: true })
    await nextTick()
    s.status.value = 'running'
    s.controller.acknowledgeSubmission('a', s.controller.submissions.value[0].id)
    await s.controller.submit()
    expect(pauseTurn).toHaveBeenCalledTimes(1)
    gate.resolve(); await sending
  })
})
