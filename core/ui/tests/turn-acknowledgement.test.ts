import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { CoreAppServerClient, CoreRequestAcceptanceUnknownError } from '../src/appServer/client'
import { DirectTransport } from '../src/transport/directTransport'
import { useCoreLiveComposerController } from '../src/composables/useCoreLiveComposerController'
import { createCoreAppServerRuntimeController, createCoreAppServerRuntimeState } from '../src/appServer/store'

class Socket {
  readyState = 0
  sent: Array<{ id: string; method: string; params: Record<string, unknown> }> = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send(value: string) { this.sent.push(JSON.parse(value)) }
  close() { this.readyState = 3; this.onclose?.() }
  emit(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) }) }
}

async function fixture() {
  const socket = new Socket()
  const transport = new DirectTransport({ apiBase: 'http://127.0.0.1:1/api/core', webSocketFactory: () => socket as unknown as WebSocket })
  const events: unknown[] = []
  const client = new CoreAppServerClient({ transport, clientInfo: { name: 'acceptance' }, onEvent: event => events.push(event) })
  const connection = client.connect()
  socket.readyState = 1; socket.onopen?.()
  await vi.advanceTimersByTimeAsync(0)
  socket.emit({ id: socket.sent[0].id, result: {} })
  await connection
  return { socket, client, events }
}

const params = { thread_id: 'thread', client_message_id: 'send-once', input: [{ type: 'text', text: 'task' }] }
const event = { event_id: 'accepted', thread_id: 'thread', client_message_id: 'send-once', turn_id: 'turn', seq: 1, method: 'turn/accepted', payload: {}, created_at: '' }

afterEach(() => vi.useRealTimers())

describe('committed turn acceptance', () => {
  it('retires an uncertain Resume after late acceptance so a later Stop/Resume is a new execution', async () => {
    const ids: unknown[] = []
    let onEvent!: (value: typeof event) => void
    const controller = createCoreAppServerRuntimeController(createCoreAppServerRuntimeState(), {
      createClient: callbacks => {
        onEvent = callbacks.onEvent
        return {
          connect: async () => {}, close: () => {}, respondServerRequest: () => false,
          request: async (method, input = {}) => {
            if (method === 'turn/resume') {
              ids.push(input.client_message_id)
              if (ids.length === 1) throw new CoreRequestAcceptanceUnknownError(String(ids[0]), new Error('lost'))
            }
            return {}
          },
        }
      },
    })
    await controller.connect('thread')
    await expect(controller.resumeTurn('thread', 'turn')).rejects.toBeInstanceOf(CoreRequestAcceptanceUnknownError)
    onEvent({ ...event, method: 'turn/started', client_message_id: String(ids[0]), payload: { resumed: true, run_id: 'first' } })
    await controller.resumeTurn('thread', 'turn')
    expect(ids[1]).not.toBe(ids[0])
    controller.disconnect()
  })

  it('reuses an uncertain Resume id on the next explicit attempt', async () => {
    const ids: unknown[] = []
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => ({
        connect: async () => {}, close: () => {}, respondServerRequest: () => false,
        request: async (method, input = {}) => {
          if (method === 'turn/resume') {
            ids.push(input.client_message_id)
            if (ids.length === 1) throw new CoreRequestAcceptanceUnknownError(String(ids[0]), new Error('lost'))
          }
          return {}
        },
      }),
    })
    await controller.connect('thread')
    await expect(controller.resumeTurn('thread', 'turn')).rejects.toBeInstanceOf(CoreRequestAcceptanceUnknownError)
    await controller.resumeTurn('thread', 'turn')
    expect(ids).toHaveLength(2)
    expect(ids[0]).toBeTruthy()
    expect(ids[1]).toBe(ids[0])
    controller.disconnect()
  })

  it('settles before acknowledgement even while the Agent is still running', async () => {
    vi.useFakeTimers()
    const { socket, client, events } = await fixture()
    const result = client.request('turn/start', params, 60_000)
    await vi.advanceTimersByTimeAsync(0)
    socket.emit({ method: 'turn/accepted', params: event })
    expect(await result).toEqual({ events: [event] })
    await vi.advanceTimersByTimeAsync(65_000)
    expect(socket.sent.filter(x => x.method === 'turn/start')).toHaveLength(1)
    expect(events).toEqual([event])
    client.close()
  })

  it('recovers acceptance at 60.5s after timeout with the same key, not a second input', async () => {
    vi.useFakeTimers()
    const { socket, client } = await fixture()
    const result = client.request('turn/start', params, 60_000)
    await vi.advanceTimersByTimeAsync(60_000)
    const sends = socket.sent.filter(x => x.method === 'turn/start')
    expect(sends).toHaveLength(2)
    expect(sends[1].params).toEqual(sends[0].params)
    await vi.advanceTimersByTimeAsync(500)
    // The original reply is late and no longer owns an RPC waiter. The
    // durable event still settles the submission and cancels reconciliation.
    socket.emit({ id: sends[0].id, result: { events: [event] } })
    socket.emit({ method: 'turn/accepted', params: event })
    expect(await result).toEqual({ events: [event] })
    client.close()
  })

  it('does not confuse another thread/key or Agent completion with acceptance', async () => {
    vi.useFakeTimers()
    const { socket, client } = await fixture()
    const promise = client.request('turn/start', params, 60_000).catch(error => error)
    await vi.advanceTimersByTimeAsync(0)
    socket.emit({ method: 'turn/accepted', params: { ...event, thread_id: 'other' } })
    socket.emit({ method: 'turn/accepted', params: { ...event, client_message_id: 'other' } })
    socket.emit({ method: 'core/runItem', params: { ...event, method: 'core/runItem', payload: { status: 'completed' } } })
    await vi.advanceTimersByTimeAsync(65_000)
    expect(await promise).toBeInstanceOf(CoreRequestAcceptanceUnknownError)
    client.close()
  })

  it('uses the correlated same-turn Resume receipt without waiting for execution', async () => {
    vi.useFakeTimers()
    const { socket, client } = await fixture()
    const result = client.request('turn/resume', { ...params, turn_id: 'turn' }, 30_000)
    await vi.advanceTimersByTimeAsync(0)
    const resumed = { ...event, method: 'turn/started', payload: { resumed: true, run_id: 'new-execution' } }
    socket.emit({ method: 'turn/started', params: resumed })
    expect(await result).toEqual({ turn_id: 'turn', events: [resumed] })
    client.close()
  })

  it('preserves the identity of a manually retried uncertain submission despite late running state', async () => {
    const text = ref('task'); const status = ref('idle'); const ids: string[] = []; let queued = 0
    const composer = useCoreLiveComposerController({
      activeThreadId: ref('thread'), connectedThreadId: ref('thread'), connectionState: ref('open'),
      text, status, cursor: ref(4), attachments: ref([]), connect: async () => {},
      startTurn: async (_thread, _input, _root, _options, id) => {
        ids.push(id!)
        if (ids.length === 1) throw new CoreRequestAcceptanceUnknownError(id!, new Error('lost receipt'))
      },
      queueInput: async () => { queued++ }, interruptTurn: async () => {}, forceResetTurn: async () => {},
      listCommands: async () => [], getWorkRoot: () => '', executeCommand: async () => true,
      clearComposer: () => { text.value = '' },
    })
    await composer.submit({ clearComposer: true })
    expect(text.value).toBe('task')
    status.value = 'running'
    await composer.submit({ clearComposer: true })
    expect(ids).toHaveLength(2)
    expect(ids[1]).toBe(ids[0])
    expect(queued).toBe(0)
    expect(text.value).toBe('')
  })
})
