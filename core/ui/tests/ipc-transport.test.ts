// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import { createIpcTransport } from '../src/transport/ipcTransport.ts'
import type { TransportMessage } from '../src/transport/types.ts'

type Handler = (event: { payload: unknown }) => void

function harness() {
  const handlers: Handler[] = []
  const transport = createIpcTransport({
    invoke: async () => ({}),
    listen: async (_event: string, handler: Handler) => {
      handlers.push(handler)
      return () => {}
    },
  })
  return {
    transport,
    emit(payload: unknown) {
      for (const handler of handlers) handler({ payload })
    },
  }
}

/**
 * user:“手机版发一条消息之后它不会回我……等一段时间把软件退出再重进才行”+
 * (手机本地 Core 的通道必须像直连一样，把 notification 的 params 拆出来。
 * 整帧塞进 params 时事件没有 thread_id / seq / payload，界面会静默丢掉每条
 * 直播事件，只有重启后 HTTP 拉历史才看得到回复。)
 */
describe('ipc transport event envelope', () => {
  it('passes the event envelope as params, not the wire frame', async () => {
    const { transport, emit } = harness()
    const seen: TransportMessage[] = []
    await transport.connect()
    transport.subscribe((message) => seen.push(message))

    const envelope = { method: 'core/runItem', thread_id: 't1', seq: 7, payload: { item: { id: 'i1' } } }
    emit({ method: 'core/runItem', params: envelope })

    expect(seen).toHaveLength(1)
    expect(seen[0].type).toBe('notification')
    expect(seen[0].method).toBe('core/runItem')
    expect(seen[0].params).toEqual(envelope)
    expect(seen[0].params?.thread_id).toBe('t1')
    expect(seen[0].params?.seq).toBe(7)
  })

  it('delivers snapshots with the snapshot object', async () => {
    const { transport, emit } = harness()
    const seen: TransportMessage[] = []
    await transport.connect()
    transport.subscribe((message) => seen.push(message))

    const snapshot = { thread_id: 't1', snapshot_revision: 3, items: [{ id: 'i1' }] }
    emit({ method: 'thread/snapshot', params: snapshot })

    expect(seen[0].method).toBe('thread/snapshot')
    expect(seen[0].params).toEqual(snapshot)
  })

  it('keeps server-initiated requests addressable', async () => {
    const { transport, emit } = harness()
    const seen: TransportMessage[] = []
    await transport.connect()
    transport.subscribe((message) => seen.push(message))

    emit({ id: 'req-9', method: 'approval/request', params: { request_id: 'req-9' } })

    expect(seen[0].type).toBe('request')
    expect(seen[0].id).toBe('req-9')
    expect(seen[0].params).toEqual({ request_id: 'req-9' })
  })
})
