import { describe, expect, it } from 'vitest'
import { createCoreAppServerRuntimeController, createCoreAppServerRuntimeState } from '../src/appServer/store.ts'
import type { CoreAppEvent, CoreAppSnapshot } from '../src/appServer/protocol.ts'

// user:“界面上的引导队列里面，还是有一条”+(已发送条目必须随实时通知移除，不能等下一份快照)。
describe('live queue consumption', () => {
  it.each(['queue/itemDispatched', 'queue/itemDeleted'])('removes consumed reminders on %s', async (method) => {
    let receive!: (event: CoreAppEvent) => void
    const runtime = createCoreAppServerRuntimeState()
    const initial = {
      thread_id: 't', snapshot_seq: 1, revision: 1, status: 'completed',
      items: {}, item_order: [], turns: {}, requests: {},
      queue: [{ queue_item_id: 'q', status: 'queued', mode: 'next_turn', goal_continuation: true,
        input: [{ type: 'text', text: '存在目标：finish 未完成，请继续。' }] }],
    } as CoreAppSnapshot
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        receive = callbacks.onEvent
        return {
          connect: async () => {}, close: () => {}, respondServerRequest: () => true,
          request: async () => ({ snapshot: initial }),
        }
      },
    })
    await controller.connect('t')
    expect(runtime.state?.queue).toHaveLength(1)
    const event = { event_id: 'consume', thread_id: 't', seq: 2, method, item_id: 'q',
      created_at: '', payload: { queue_item_id: 'q', status: 'dispatched' } } as CoreAppEvent
    receive(event)
    expect(runtime.state?.queue).toEqual([])
    // A delayed pre-consumption snapshot must not resurrect the reminder.
    controller.hydrate(initial)
    expect(runtime.state?.queue).toEqual([])
    controller.disconnect()
  })
})
