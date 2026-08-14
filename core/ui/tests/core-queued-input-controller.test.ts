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
})
