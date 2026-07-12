import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { useCoreLiveTurnController } from '../src/composables'

describe('useCoreLiveTurnController', () => {
  it('connects the active thread before starting a Core turn', async () => {
    const calls: string[] = []
    const activeThreadId = ref<string | null>('thread-1')
    const connectedThreadId = ref('')
    const connectionState = ref<'connecting' | 'open' | 'closed' | 'error'>('closed')
    const controller = useCoreLiveTurnController({
      activeThreadId,
      connectedThreadId,
      connectionState,
      connect: async (threadId) => {
        calls.push(`connect:${threadId}`)
        connectedThreadId.value = threadId
        connectionState.value = 'open'
      },
      startTurn: async (threadId, input, workRoot, options) => {
        calls.push(`start:${threadId}:${JSON.stringify(input)}:${workRoot}:${String(options.thinking_enabled)}`)
      },
      interruptTurn: async () => {
        throw new Error('not used')
      },
    })

    const started = await controller.startActiveTurn(
      [{ type: 'text', text: 'write a document' }],
      'E:\\LamTools',
      { thinking_enabled: true },
    )

    expect(started).toBe(true)
    expect(calls).toEqual([
      'connect:thread-1',
      'start:thread-1:[{"type":"text","text":"write a document"}]:E:\\LamTools:true',
    ])
    expect(controller.isActiveThreadConnected.value).toBe(true)
  })

  it('stops an already connected active turn without reconnecting', async () => {
    const calls: string[] = []
    const controller = useCoreLiveTurnController({
      activeThreadId: ref<string | null>('thread-1'),
      connectedThreadId: ref('thread-1'),
      connectionState: ref<'connecting' | 'open' | 'closed' | 'error'>('open'),
      connect: async () => {
        calls.push('connect')
      },
      startTurn: async () => {
        throw new Error('not used')
      },
      interruptTurn: async (threadId) => {
        calls.push(`interrupt:${threadId}`)
      },
    })

    expect(await controller.interruptActiveTurn()).toBe(true)
    expect(calls).toEqual(['interrupt:thread-1'])
  })

  it('starts an explicitly captured thread without rereading the active thread', async () => {
    const calls: string[] = []
    const controller = useCoreLiveTurnController({
      activeThreadId: ref<string | null>('thread-b'),
      connectedThreadId: ref('thread-a'),
      connectionState: ref<'connecting' | 'open' | 'closed' | 'error'>('open'),
      connect: async (threadId) => calls.push(`connect:${threadId}`),
      startTurn: async (threadId, _input, workRoot, options) => {
        calls.push(`start:${threadId}:${workRoot}:${String(options.model_id)}`)
      },
      interruptTurn: async () => undefined,
    })

    expect(await controller.startThreadTurn([{ type: 'text', text: 'from A' }], 'thread-a', 'E:\\A', { model_id: 'model-a' })).toBe(true)
    expect(calls).toEqual(['start:thread-a:E:\\A:model-a'])
  })
})
