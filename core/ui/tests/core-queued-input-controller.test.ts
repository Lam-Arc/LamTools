import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { useCoreQueuedInputController } from '../src/composables'

describe('useCoreQueuedInputController', () => {
  it('saves an edited queued input before steering it into the active turn', async () => {
    const calls: string[] = []
    let resolveGuidance!: (value: { applied: boolean; reason: string }) => void
    const activeTurnId = ref('turn-1')
    const controller = useCoreQueuedInputController({
      activeTurnId,
      ensureConnected: async (threadId) => {
        calls.push(`connect:${threadId}`)
      },
      updateQueueInput: async (threadId, itemId, text) => {
        calls.push(`update:${threadId}:${itemId}:${text}`)
      },
      deleteQueueInput: async (threadId, itemId) => {
        calls.push(`delete:${threadId}:${itemId}`)
      },
      reorderQueueInputs: async (threadId, order) => {
        calls.push(`reorder:${threadId}:${order.join(',')}`)
      },
      guideQueueInput: async (threadId, turnId, itemId, text) => {
        calls.push(`guide:${threadId}:${turnId}:${itemId}:${text}`)
        return await new Promise(resolve => { resolveGuidance = resolve })
      },
    })
    const item = { id: 'queue-1', thread_id: 'thread-1', text: 'old text', status: 'queued' }

    await controller.beginEdit(item)
    controller.draft.value = 'updated text'
    const pending = controller.guide(item)
    const duplicate = controller.guide(item)
    await Promise.resolve()

    expect(calls).toEqual([
      'connect:thread-1',
      'guide:thread-1:turn-1:queue-1:updated text',
    ])
    expect([...controller.submittingItemIds.value]).toEqual(['queue-1'])
    await expect(duplicate).resolves.toBe(false)
    resolveGuidance?.({ applied: true, reason: '' })
    await expect(pending).resolves.toBe(true)
    expect([...controller.submittingItemIds.value]).toEqual([])
    expect(controller.editingId.value).toBeNull()
    expect(controller.draft.value).toBe('')
  })

  it('does not guide a queued input without an active steerable turn', async () => {
    const activeTurnId = ref('')
    const controller = useCoreQueuedInputController({
      activeTurnId,
      ensureConnected: async () => {
        throw new Error('must not connect')
      },
      updateQueueInput: async () => {
        throw new Error('must not update')
      },
      deleteQueueInput: async () => {
        throw new Error('must not delete')
      },
      reorderQueueInputs: async () => {
        throw new Error('must not reorder')
      },
      guideQueueInput: async () => {
        throw new Error('must not guide')
      },
    })

    const result = await controller.guide({
      id: 'queue-1',
      thread_id: 'thread-1',
      text: 'follow up',
      status: 'queued',
    })

    expect(controller.canGuide.value).toBe(false)
    expect(result).toBe(false)
  })

  it('submits the dragged order once and ignores overlapping drags', async () => {
    // user:“排队项可拖拽上下移动重新排序”+(一次拖拽提交一份完整新顺序；写请求在途
    //   时忽略后续拖拽，失败时把错误交给 onError，顺序由服务端事件统一回放)。
    const calls: string[][] = []
    let releaseOrder!: (value: { applied: boolean; reason: string }) => void
    const errors: unknown[] = []
    const activeTurnId = ref('turn-1')
    const controller = useCoreQueuedInputController({
      activeTurnId,
      ensureConnected: async () => undefined,
      updateQueueInput: async () => undefined,
      deleteQueueInput: async () => undefined,
      reorderQueueInputs: async (_threadId, order) => {
        calls.push(order)
        await new Promise<{ applied: boolean; reason: string }>(resolve => { releaseOrder = resolve })
      },
      guideQueueInput: async () => ({ applied: true, reason: '' }),
      onError: (error) => { errors.push(error) },
    })
    const items = [
      { id: 'a', thread_id: 'thread-1', text: 'one', status: 'queued' },
      { id: 'b', thread_id: 'thread-1', text: 'two', status: 'queued' },
      { id: 'c', thread_id: 'thread-1', text: 'three', status: 'queued' },
    ]

    const pending = controller.reorder([items[2], items[0], items[1]])
    // 在途的重排请求要挡住紧跟的第二次拖拽：只允许一份新顺序在写。
    const overlapping = controller.reorder([items[1], items[2], items[0]])
    await expect(overlapping).resolves.toBe(false)
    expect(calls).toEqual([['c', 'a', 'b']])
    releaseOrder?.({ applied: true, reason: '' })
    await expect(pending).resolves.toBe(true)
    expect(calls).toEqual([['c', 'a', 'b']])
    expect(controller.reordering.value).toBe(false)

    // 失败要上报，不能静默吞掉。
    const failing = useCoreQueuedInputController({
      activeTurnId,
      ensureConnected: async () => undefined,
      updateQueueInput: async () => undefined,
      deleteQueueInput: async () => undefined,
      reorderQueueInputs: async () => {
        throw new Error('reorder unavailable')
      },
      guideQueueInput: async () => ({ applied: true, reason: '' }),
      onError: (error) => { errors.push(error) },
    })
    await expect(failing.reorder(items)).resolves.toBe(false)
    expect(errors).toHaveLength(1)
    expect(failing.lastError.value).toBe('reorder unavailable')
  })
})
