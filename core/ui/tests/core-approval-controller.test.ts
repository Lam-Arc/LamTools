import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { useCoreApprovalController } from '../src/composables'
import type { CoreMessage } from '../src/types'

describe('useCoreApprovalController', () => {
  it('marks an approval request as submitting until the Core response finishes', async () => {
    let resolveResponse: (() => void) | null = null
    const calls: string[] = []
    const messages = ref<CoreMessage[]>([{
      id: 'assistant-1',
      role: 'assistant',
      content: '',
      timestamp: '',
      parts: [{
        id: 'approval-1',
        partType: 'decision',
        status: 'pending',
        content: 'Need approval',
        metadata: { waitingRequest: { request_id: 'request-1' } },
      }],
    }])
    const controller = useCoreApprovalController({
      messages,
      hasActiveThread: ref(true),
      canRespondApproval: ref(true),
      respondApproval: async (requestId, decision, guidance) => {
        calls.push(`${requestId}:${decision}:${guidance}`)
        await new Promise<void>((resolve) => { resolveResponse = resolve })
      },
      submitText: async () => {
        throw new Error('not used')
      },
      deferText: () => {
        throw new Error('not used')
      },
    })

    const pending = controller.handleDecision({
      partId: 'approval-1',
      option: { id: 'approve_once' },
      response: 'allow this run',
    })

    expect([...controller.submittingRequestIds.value]).toEqual(['request-1'])
    resolveResponse?.()
    await expect(pending).resolves.toBe('approval')
    expect(calls).toEqual(['request-1:approve_once:allow this run'])
    expect([...controller.submittingRequestIds.value]).toEqual([])
  })

  it('falls back to ordinary text when an approval cannot use the live channel', async () => {
    const submitted: string[] = []
    const controller = useCoreApprovalController({
      messages: ref([]),
      hasActiveThread: ref(true),
      canRespondApproval: ref(false),
      respondApproval: async () => {
        throw new Error('not used')
      },
      submitText: async (text) => {
        submitted.push(text)
      },
      deferText: () => {
        throw new Error('not used')
      },
    })

    await expect(controller.handleDecision({
      partId: 'missing',
      option: { id: 'other_guidance' },
      response: 'use a read-only path',
    })).resolves.toBe('text')

    expect(submitted).toEqual(['use a read-only path'])
  })

  it('keeps a real approval pending when its live channel cannot be restored', async () => {
    const submitted: string[] = []
    const controller = useCoreApprovalController({
      messages: ref<CoreMessage[]>([{
        id: 'assistant-1',
        role: 'assistant',
        content: '',
        timestamp: '',
        parts: [{
          id: 'approval-1',
          partType: 'decision',
          status: 'pending',
          content: 'Need approval',
          metadata: { waitingRequest: { request_id: 'request-1' } },
        }],
      }]),
      hasActiveThread: ref(true),
      canRespondApproval: ref(false),
      ensureApprovalChannel: async () => false,
      respondApproval: async () => {
        throw new Error('must not respond')
      },
      submitText: async (text) => {
        submitted.push(text)
      },
      deferText: () => {
        throw new Error('must not defer into the composer')
      },
    })

    await expect(controller.handleDecision({
      partId: 'approval-1',
      option: { id: 'deny' },
      response: 'do not run',
    })).resolves.toBe('deferred')

    expect(submitted).toEqual([])
    expect(controller.lastError.value).toBe('Approval channel is unavailable')
  })
})
