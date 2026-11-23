import { beforeEach, describe, expect, it } from 'vitest'
import { createCoreAppServerRuntimeController, createCoreAppServerRuntimeState } from '../src/appServer/store.ts'
import { __resetCoreToastStoreForTests, useCoreToast } from '../src/composables/useCoreToast.ts'
import type { CoreAppEvent, CoreAppSnapshot } from '../src/appServer/protocol.ts'

// user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(关键指标超出阈值时
// 要给界面一条可见的轻量告警，不能只写后端日志——上次故障就是因为前端毫无感知。)
describe('backpressure notice', () => {
  beforeEach(() => {
    __resetCoreToastStoreForTests()
  })

  it('ignores a legacy notice for 400 skipped progress frames with an empty reliable queue', async () => {
    let receive!: (event: CoreAppEvent) => void
    const runtime = createCoreAppServerRuntimeState()
    const initial = {
      thread_id: 't', snapshot_seq: 1, revision: 1, status: 'completed',
      items: {}, item_order: [], turns: {}, requests: {}, queue: [],
    } as unknown as CoreAppSnapshot
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

    receive({
      thread_id: 't',
      method: 'core/backpressure',
      payload: {},
      params: {},
      control_queue_depth: 0,
      control_queue_limit: 64,
      lossy_dropped: 400,
      lossy_merged: 15073,
      wal_pending_pages: 1234,
      reason: 'lossy_lane_pressure',
    } as unknown as CoreAppEvent)

    expect(useCoreToast().toasts.value).toHaveLength(0)
    // 控制通知不能改写会话状态。
    expect(runtime.state?.thread_id).toBe('t')
    controller.disconnect()
  })

  it.each(['control_queue_pressure', 'lossy_lane_pressure'])('shows reliable backlog for %s', async (reason) => {
    let receive!: (event: CoreAppEvent) => void
    const runtime = createCoreAppServerRuntimeState()
    const initial = {
      thread_id: 't', snapshot_seq: 1, revision: 1, status: 'completed',
      items: {}, item_order: [], turns: {}, requests: {}, queue: [],
    } as unknown as CoreAppSnapshot
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

    receive({
      thread_id: 't',
      method: 'core/backpressure',
      payload: {},
      control_queue_depth: 40,
      control_queue_limit: 64,
      lossy_dropped: 400,
      wal_pending_pages: 1234,
      reason,
    } as unknown as CoreAppEvent)

    expect(useCoreToast().toasts.value).toHaveLength(1)
    const notice = useCoreToast().toasts.value[0]
    expect(notice.kind).toBe('notice')
    expect(notice.text).toBe('消息较多，会话更新可能延迟。')
    controller.disconnect()
  })
})
