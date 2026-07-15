import { nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { useCoreLiveComposerController } from '../src/composables'
import type { CoreInputItem } from '../src'

const commands = [
  { name: 'compact', title: 'Compact', description: '', icon: '/', source: 'core', action: 'run_action' },
  { name: 'reviewer', title: 'Reviewer', description: '', icon: '/', source: 'member', action: 'insert_token' },
] as const

describe('useCoreLiveComposerController', () => {
  it('starts the captured thread with its captured work root and turn options after a session switch', async () => {
    const activeThreadId = ref<string | null>('thread-a')
    const connectedThreadId = ref('')
    const connectionState = ref<'connecting' | 'open' | 'closed' | 'error'>('closed')
    const text = ref('write from A')
    const started: Array<{ threadId: string; workRoot?: string; options?: Record<string, unknown> }> = []
    const controller = useCoreLiveComposerController({
      activeThreadId,
      connectedThreadId,
      connectionState,
      text,
      cursor: ref(text.value.length),
      status: ref('idle'),
      attachments: ref<CoreInputItem[]>([]),
      connect: async (threadId) => {
        connectedThreadId.value = threadId
        connectionState.value = 'open'
        activeThreadId.value = 'thread-b'
      },
      startTurn: async (threadId, _input, workRoot, options) => {
        started.push({ threadId, workRoot, options })
      },
      interruptTurn: async () => undefined,
      queueInput: async () => undefined,
      listCommands: async () => [],
      getWorkRoot: () => activeThreadId.value === 'thread-a' ? 'E:\\A' : 'E:\\B',
      turnOptions: () => ({ model_id: activeThreadId.value === 'thread-a' ? 'model-a' : 'model-b' }),
      executeCommand: async () => true,
    })

    await controller.submit({ clearComposer: true })

    expect(started).toEqual([{
      threadId: 'thread-a',
      workRoot: 'E:\\A',
      options: { model_id: 'model-a' },
    }])
  })

  it('keeps a successful turn successful when the post-start callback fails', async () => {
    const text = ref('write a test')
    const attachments = ref<CoreInputItem[]>([{ type: 'attachment', attachment_id: 'a-1' }])
    const errors: string[] = []
    let clearedText = ''
    let clearedAttachments = 0
    const controller = useCoreLiveComposerController({
      activeThreadId: ref<string | null>('thread-1'),
      connectedThreadId: ref('thread-1'),
      connectionState: ref<'connecting' | 'open' | 'closed' | 'error'>('open'),
      text,
      cursor: ref(text.value.length),
      status: ref('idle'),
      attachments,
      connect: async () => undefined,
      startTurn: async () => undefined,
      interruptTurn: async () => undefined,
      queueInput: async () => undefined,
      listCommands: async () => [],
      getWorkRoot: () => 'E:\\LamTools',
      executeCommand: async () => true,
      clearComposer: (value) => {
        clearedText = value
        text.value = ''
      },
      clearAttachments: () => {
        clearedAttachments += 1
        attachments.value = []
      },
      onTurnStarted: async () => {
        throw new Error('refresh failed')
      },
      onTurnStartedError: (error) => errors.push(error instanceof Error ? error.message : String(error)),
    })

    await expect(controller.submit({ clearComposer: true })).resolves.toMatchObject({ status: 'started', ok: true })
    await Promise.resolve()

    expect(clearedText).toBe('write a test')
    expect(clearedAttachments).toBe(1)
    expect(errors).toEqual(['refresh failed'])
  })

  it('ignores stale command catalog success and failure after a thread change', async () => {
    const activeThreadId = ref<string | null>('thread-a')
    const connectedThreadId = ref('thread-a')
    const connectionState = ref<'connecting' | 'open' | 'closed' | 'error'>('open')
    let resolveA: (value: unknown[]) => void = () => undefined
    let resolveB: (value: unknown[]) => void = () => undefined
    let rejectLate: (reason?: unknown) => void = () => undefined
    const catalogA = new Promise<unknown[]>((resolve) => {
      resolveA = resolve
    })
    const catalogB = new Promise<unknown[]>((resolve) => {
      resolveB = resolve
    })
    const lateFailure = new Promise<unknown[]>((_resolve, reject) => {
      rejectLate = reject
    })
    let catalogRequestCount = 0
    const controller = useCoreLiveComposerController({
      activeThreadId,
      connectedThreadId,
      connectionState,
      text: ref(''),
      cursor: ref(0),
      status: ref('idle'),
      attachments: ref<CoreInputItem[]>([]),
      connect: async (threadId) => {
        connectedThreadId.value = threadId
      },
      startTurn: async () => undefined,
      interruptTurn: async () => undefined,
      queueInput: async () => undefined,
      listCommands: async () => {
        catalogRequestCount += 1
        if (catalogRequestCount === 1) return await catalogA
        if (catalogRequestCount === 2) return await catalogB
        return await lateFailure
      },
      getWorkRoot: () => activeThreadId.value === 'thread-a' ? 'E:\\A' : 'E:\\B',
      executeCommand: async () => true,
    })

    const loadingA = controller.loadCommandCatalog()
    await Promise.resolve()
    activeThreadId.value = 'thread-b'
    controller.resetForThreadChange()
    const loadingB = controller.loadCommandCatalog()
    await Promise.resolve()
    resolveB([{ name: 'b-command' }])
    await loadingB

    resolveA([{ name: 'a-command' }])
    await loadingA
    expect(controller.commandCatalog.value.map(command => command.name)).toEqual(['b-command'])
    expect(controller.commandError.value).toBe('')

    activeThreadId.value = 'thread-a'
    const staleFailure = controller.loadCommandCatalog('thread-a')
    await Promise.resolve()
    activeThreadId.value = 'thread-b'
    controller.resetForThreadChange()
    rejectLate(new Error('A failed late'))
    await staleFailure
    expect(controller.commandCatalog.value).toEqual([])
    expect(controller.commandError.value).toBe('')
  })

  it('ignores an old catalog load invoked after the active thread moved to B', async () => {
    const calls: string[] = []
    const controller = useCoreLiveComposerController({
      activeThreadId: ref<string | null>('thread-b'),
      connectedThreadId: ref('thread-b'),
      connectionState: ref<'connecting' | 'open' | 'closed' | 'error'>('open'),
      text: ref(''),
      cursor: ref(0),
      status: ref('idle'),
      attachments: ref<CoreInputItem[]>([]),
      connect: async (threadId) => calls.push(`connect:${threadId}`),
      startTurn: async () => undefined,
      interruptTurn: async () => undefined,
      queueInput: async () => undefined,
      listCommands: async () => {
        calls.push('list')
        return []
      },
      getWorkRoot: () => 'E:\\B',
      executeCommand: async () => true,
      setStatusText: (text) => calls.push(`status:${text}`),
    })
    controller.commandCatalog.value = [{
      name: 'b-command', title: 'B command', description: '', icon: '/', source: 'core', action: 'run_action',
    }]

    await expect(controller.loadCommandCatalog('thread-a')).resolves.toBe(false)

    expect(calls).toEqual([])
    expect(controller.commandCatalog.value.map(command => command.name)).toEqual(['b-command'])
    expect(controller.commandError.value).toBe('')
  })

  it('runs a command against the thread and work root captured before connection', async () => {
    const activeThreadId = ref<string | null>('thread-a')
    const connectedThreadId = ref('')
    const connectionState = ref<'connecting' | 'open' | 'closed' | 'error'>('closed')
    const calls: string[] = []
    const controller = useCoreLiveComposerController({
      activeThreadId,
      connectedThreadId,
      connectionState,
      text: ref(''),
      cursor: ref(0),
      status: ref('idle'),
      attachments: ref<CoreInputItem[]>([]),
      connect: async (threadId) => {
        calls.push(`connect:${threadId}`)
        connectedThreadId.value = threadId
        connectionState.value = 'open'
        activeThreadId.value = 'thread-b'
      },
      startTurn: async () => undefined,
      interruptTurn: async () => undefined,
      queueInput: async () => undefined,
      listCommands: async () => [],
      getWorkRoot: () => activeThreadId.value === 'thread-a' ? 'E:\\A' : 'E:\\B',
      executeCommand: async (threadId, command, workRoot) => {
        calls.push(`command:${threadId}:${command}:${workRoot}`)
        return true
      },
    })

    await expect(controller.runCommand('compact')).resolves.toBe(true)

    expect(calls).toEqual(['connect:thread-a', 'command:thread-a:compact:E:\\A'])
  })

  it('clears a running action command immediately and exposes stop until it settles', async () => {
    const text = ref('/compact')
    const status = ref('running')
    let resolveCommand: (value: boolean) => void = () => undefined
    const commandResult = new Promise<boolean>((resolve) => {
      resolveCommand = resolve
    })
    const controller = useCoreLiveComposerController({
      activeThreadId: ref<string | null>('thread-1'),
      activeTurnId: ref('thread-1:command:compact:running'),
      connectedThreadId: ref('thread-1'),
      connectionState: ref<'connecting' | 'open' | 'closed' | 'error'>('open'),
      text,
      cursor: ref(text.value.length),
      status,
      attachments: ref<CoreInputItem[]>([]),
      connect: async () => undefined,
      startTurn: async () => undefined,
      interruptTurn: async () => undefined,
      queueInput: async () => undefined,
      listCommands: async () => commands,
      getWorkRoot: () => 'E:\\LamTools',
      executeCommand: async () => commandResult,
    })
    controller.commandCatalog.value = [...commands]

    const submission = controller.submit({ clearComposer: true })
    await Promise.resolve()

    expect(text.value).toBe('')
    expect(controller.actionMode.value).toBe('stop')

    status.value = 'completed'
    resolveCommand(true)
    await submission
    expect(controller.actionMode.value).toBe('send')
  })

  it('owns command loading, palette selection, and live submission effects', async () => {
    const calls: string[] = []
    const activeThreadId = ref<string | null>('thread-1')
    const connectedThreadId = ref('')
    const connectionState = ref<'connecting' | 'open' | 'closed' | 'error'>('closed')
    const text = ref('/')
    const cursor = ref(1)
    const status = ref('idle')
    const attachments = ref<CoreInputItem[]>([])
    const statusText = ref('')
    const clearedTexts: string[] = []
    let clearedAttachments = 0

    const controller = useCoreLiveComposerController({
      activeThreadId,
      connectedThreadId,
      connectionState,
      text,
      cursor,
      status,
      attachments,
      connect: async (threadId) => {
        calls.push(`connect:${threadId}`)
        connectedThreadId.value = threadId
        connectionState.value = 'open'
      },
      startTurn: async (threadId, input) => {
        calls.push(`start:${threadId}:${JSON.stringify(input)}`)
      },
      interruptTurn: async (threadId) => {
        calls.push(`stop:${threadId}`)
      },
      queueInput: async (threadId, input) => {
        calls.push(`queue:${threadId}:${JSON.stringify(input)}`)
      },
      listCommands: async () => commands,
      getWorkRoot: () => 'E:\\LamTools',
      executeCommand: async (threadId, command, workRoot) => {
        calls.push(`command:${threadId}:${command}:${workRoot}`)
        return true
      },
      clearComposer: (submittedText) => {
        clearedTexts.push(submittedText)
        if (text.value.trim() === submittedText) text.value = ''
      },
      clearAttachments: () => {
        clearedAttachments += 1
        attachments.value = []
      },
      setStatusText: (value) => {
        statusText.value = value
      },
      messages: {
        queued: 'Queued by member',
        stopping: 'Stopping by member',
      },
    })

    await controller.loadCommandCatalog()
    expect(controller.commandCatalog.value.map(command => command.name)).toEqual(['compact', 'reviewer'])
    expect(controller.commandError.value).toBe('')
    expect(calls).toEqual(['connect:thread-1'])

    await controller.handleKeydown(new KeyboardEvent('keydown', { key: 'ArrowDown' }))
    await controller.handleKeydown(new KeyboardEvent('keydown', { key: 'Enter' }))
    expect(text.value).toBe('/reviewer')
    expect(controller.paletteVisible.value).toBe(false)

    text.value = '/compact'
    cursor.value = text.value.length
    await controller.selectCommand(commands[0])
    expect(calls).toContain('command:thread-1:compact:E:\\LamTools')
    expect(text.value).toBe('')

    text.value = 'stop now'
    status.value = 'running'
    await controller.submit({ clearComposer: true })
    expect(calls).toContain('queue:thread-1:[{"type":"text","text":"stop now"}]')
    expect(statusText.value).toBe('Queued by member')
    expect(clearedTexts).toContain('stop now')

    text.value = ''
    await controller.submit({ clearComposer: true })
    expect(calls).toContain('stop:thread-1')
    expect(statusText.value).toBe('Stopping by member')
    status.value = 'cancelled'
    await nextTick()
    expect(statusText.value).toBe('')

    status.value = 'idle'
    text.value = 'write a test'
    attachments.value = [{ type: 'attachment', attachment_id: 'a-1' }]
    await controller.submit({ clearComposer: true })
    expect(calls).toContain('start:thread-1:[{"type":"text","text":"write a test"},{"type":"attachment","attachment_id":"a-1"}]')
    expect(statusText.value).toBe('')
    expect(clearedAttachments).toBe(1)
  })

  it('exposes command catalog failures without hiding the underlying error', async () => {
    const controller = useCoreLiveComposerController({
      activeThreadId: ref<string | null>('thread-1'),
      connectedThreadId: ref('thread-1'),
      connectionState: ref<'connecting' | 'open' | 'closed' | 'error'>('open'),
      text: ref(''),
      cursor: ref(0),
      status: ref('idle'),
      attachments: ref<CoreInputItem[]>([]),
      connect: async () => undefined,
      startTurn: async () => undefined,
      interruptTurn: async () => undefined,
      queueInput: async () => undefined,
      listCommands: async () => {
        throw new Error('catalog unavailable')
      },
      getWorkRoot: () => '',
      executeCommand: async () => true,
      setStatusText: () => undefined,
    })

    await controller.loadCommandCatalog()
    expect(controller.commandCatalog.value).toEqual([])
    expect(controller.commandError.value).toBe('catalog unavailable')
  })
})
