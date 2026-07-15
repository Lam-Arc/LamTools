import { nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { useCoreApprovalController } from '../src/composables'
import type { CoreMessage } from '../src/types'

describe('useCoreApprovalController', () => {
  it('keeps an approval visibly submitting until the projected request is resolved', async () => {
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
      },
      submitText: async () => {
        throw new Error('not used')
      },
      deferText: () => {
        throw new Error('not used')
      },
    })

    await expect(controller.handleDecision({
      partId: 'approval-1',
      option: { id: 'approve_once' },
      response: 'allow this run',
    })).resolves.toBe('approval')

    expect([...controller.submittingRequestIds.value]).toEqual(['request-1'])
    expect(calls).toEqual(['request-1:approve_once:allow this run'])

    messages.value = [{
      ...messages.value[0],
      parts: [{
        ...messages.value[0].parts![0],
        status: 'completed',
        metadata: {
          waitingRequest: {
            request_id: 'request-1',
            response: { decision: 'approve_once' },
          },
        },
      }],
    }]
    await nextTick()

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

  it('responds to an approval nested inside a sub-agent timeline', async () => {
    const calls: string[] = []
    const nestedApproval = {
      id: 'child-approval-1',
      partType: 'decision' as const,
      status: 'pending' as const,
      content: 'Allow child write',
      metadata: { waitingRequest: { request_id: 'child-request-1' } },
    }
    const messages = ref<CoreMessage[]>([{
      id: 'assistant-1',
      role: 'assistant',
      content: '',
      timestamp: '',
      parts: [{
        id: 'sub-agent-1',
        partType: 'agent_summary',
        status: 'pending',
        content: '',
        metadata: { subLineParts: [nestedApproval] },
      }],
    }])
    const controller = useCoreApprovalController({
      messages,
      hasActiveThread: ref(true),
      canRespondApproval: ref(true),
      respondApproval: async (requestId, decision, guidance) => {
        calls.push(`${requestId}:${decision}:${guidance}`)
      },
      submitText: async () => {
        throw new Error('must not become ordinary text')
      },
      deferText: () => {
        throw new Error('must not defer')
      },
    })

    await expect(controller.handleDecision({
      partId: 'child-approval-1',
      option: { id: 'approve' },
      response: 'approve',
    })).resolves.toBe('approval')

    expect(calls).toEqual(['child-request-1:approve_once:approve'])
    expect([...controller.submittingRequestIds.value]).toEqual(['child-request-1'])

    nestedApproval.status = 'completed'
    nestedApproval.metadata.waitingRequest = {
      request_id: 'child-request-1',
      response: { decision: 'approve_once' },
    } as typeof nestedApproval.metadata.waitingRequest
    messages.value = [{ ...messages.value[0] }]
    await nextTick()

    expect([...controller.submittingRequestIds.value]).toEqual([])
  })
})
