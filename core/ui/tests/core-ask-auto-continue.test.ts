import { effectScope, nextTick, ref, type Ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ASK_SKIP_GUIDANCE,
  ASK_SKIP_TIMEOUT_MS,
  useCoreAskAutoContinue,
} from '../src/composables/useCoreAskAutoContinue'
import type { CoreMessage } from '../src/types'

function decisionPart(
  requestId: string,
  options: { answered?: boolean; toolName?: string } = {},
) {
  return {
    id: `part-${requestId}`,
    partType: 'decision',
    status: 'pending',
    toolName: options.toolName ?? 'question',
    metadata: {
      waitingRequest: {
        kind: options.toolName === 'run_command' ? 'approval' : 'question',
        request_id: requestId,
        ...(options.answered ? { response: { decision: 'other_guidance' } } : {}),
      },
    },
  }
}

function messagesWith(parts: unknown[]): CoreMessage[] {
  return [{ id: 'm1', role: 'assistant', parts } as unknown as CoreMessage]
}

/** A delegated sub-agent row carrying the child's own waiting request nested
 *  under it — the shape a sub-agent question/approval arrives in. */
function subAgentLine(children: unknown[]): unknown {
  return {
    id: 'agent-1',
    partType: 'agent_summary',
    status: 'running',
    toolName: 'sub_agent',
    metadata: { agent_name: 'worker', sub_session_id: 'sub-1', subLineParts: children },
  }
}

function setup(options: {
  messages: Ref<CoreMessage[]>
  enabled: () => Promise<boolean>
  respondApproval?: (requestId: string, decision: string, guidance: string) => Promise<void>
  onAutoSkipped?: (requestId: string) => void
  onError?: (message: string) => void
  timeoutMs?: number
}) {
  const respondApproval = options.respondApproval ?? vi.fn(async () => {})
  const scope = effectScope()
  const api = scope.run(() => useCoreAskAutoContinue({
    messages: options.messages,
    loadEnabled: options.enabled,
    respondApproval,
    onAutoSkipped: options.onAutoSkipped,
    onError: options.onError,
    timeoutMs: options.timeoutMs,
  }))!
  return { scope, api, respondApproval }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('useCoreAskAutoContinue', () => {
  it('never auto-answers an approval card', async () => {
    vi.useFakeTimers()
    const messages = ref<CoreMessage[]>(messagesWith([decisionPart('req-approval', { toolName: 'run_command' })]))
    const loadEnabled = vi.fn(async () => true)
    const { api, respondApproval } = setup({ messages, enabled: loadEnabled })

    await nextTick()
    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS * 3)

    expect(api.armedRequestIds()).toEqual([])
    // 审批是安全边界：连偏好都不必读，更不会放行。
    expect(loadEnabled).not.toHaveBeenCalled()
    expect(respondApproval).not.toHaveBeenCalled()
  })

  it('leaves a pending approval alone while skipping a question in the same turn', async () => {
    vi.useFakeTimers()
    const messages = ref<CoreMessage[]>(messagesWith([
      decisionPart('req-approval', { toolName: 'run_command' }),
      decisionPart('req-ask'),
    ]))
    const { api, respondApproval } = setup({ messages, enabled: async () => true })

    await nextTick()
    expect(api.armedRequestIds()).toEqual(['req-ask'])

    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS)
    expect(respondApproval).toHaveBeenCalledTimes(1)
    expect(respondApproval).toHaveBeenCalledWith('req-ask', 'other_guidance', ASK_SKIP_GUIDANCE)
  })

  it('skips a question that came from a sub-agent, on the same five-minute rule', async () => {
    vi.useFakeTimers()
    const messages = ref<CoreMessage[]>(messagesWith([subAgentLine([decisionPart('req-sub-ask')])]))
    const { api, respondApproval } = setup({ messages, enabled: async () => true })

    await nextTick()
    expect(api.armedRequestIds()).toEqual(['req-sub-ask'])

    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS)
    expect(respondApproval).toHaveBeenCalledWith('req-sub-ask', 'other_guidance', ASK_SKIP_GUIDANCE)
  })

  it('never auto-answers a sub-agent approval, however deeply nested', async () => {
    vi.useFakeTimers()
    const messages = ref<CoreMessage[]>(messagesWith([
      subAgentLine([subAgentLine([decisionPart('req-sub-approval', { toolName: 'run_command' })])]),
    ]))
    const loadEnabled = vi.fn(async () => true)
    const { api, respondApproval } = setup({ messages, enabled: loadEnabled })

    await nextTick()
    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS * 3)

    expect(api.armedRequestIds()).toEqual([])
    // 子代理的审批同样是安全边界：不读偏好、不放行。
    expect(loadEnabled).not.toHaveBeenCalled()
    expect(respondApproval).not.toHaveBeenCalled()
  })

  it('does nothing while the preference is off', async () => {
    vi.useFakeTimers()
    const messages = ref<CoreMessage[]>(messagesWith([decisionPart('req-ask')]))
    const { api, respondApproval } = setup({ messages, enabled: async () => false })

    await nextTick()
    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS * 2)

    expect(api.armedRequestIds()).toEqual([])
    expect(respondApproval).not.toHaveBeenCalled()
  })

  it('reports the skip once the wait window elapses', async () => {
    vi.useFakeTimers()
    const messages = ref<CoreMessage[]>(messagesWith([decisionPart('req-ask')]))
    const skipped: string[] = []
    const { respondApproval } = setup({
      messages,
      enabled: async () => true,
      onAutoSkipped: (requestId) => skipped.push(requestId),
    })

    await nextTick()
    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS - 1)
    expect(respondApproval).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)
    expect(respondApproval).toHaveBeenCalledWith('req-ask', 'other_guidance', ASK_SKIP_GUIDANCE)
    expect(skipped).toEqual(['req-ask'])
  })

  it('drops the timer once the user answers by hand', async () => {
    vi.useFakeTimers()
    const messages = ref<CoreMessage[]>(messagesWith([decisionPart('req-ask')]))
    const { api, respondApproval } = setup({ messages, enabled: async () => true })

    await nextTick()
    expect(api.armedRequestIds()).toEqual(['req-ask'])

    messages.value = messagesWith([decisionPart('req-ask', { answered: true })])
    await nextTick()
    expect(api.armedRequestIds()).toEqual([])

    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS * 2)
    expect(respondApproval).not.toHaveBeenCalled()
  })

  it('never double-fires for the same request', async () => {
    vi.useFakeTimers()
    const messages = ref<CoreMessage[]>(messagesWith([decisionPart('req-ask')]))
    const { respondApproval } = setup({ messages, enabled: async () => true })

    await nextTick()
    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS)
    messages.value = messagesWith([decisionPart('req-ask')])
    await nextTick()
    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS * 3)

    expect(respondApproval).toHaveBeenCalledTimes(1)
  })

  it('re-arms after a failed response instead of giving up', async () => {
    vi.useFakeTimers()
    const messages = ref<CoreMessage[]>(messagesWith([decisionPart('req-ask')]))
    const errors: string[] = []
    const respondApproval = vi.fn()
      .mockRejectedValueOnce(new Error('连接中断'))
      .mockResolvedValue(undefined)
    setup({
      messages,
      enabled: async () => true,
      respondApproval,
      onError: (message) => errors.push(message),
    })

    await nextTick()
    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS)
    expect(errors).toEqual(['连接中断'])

    // A suspended turn emits no further snapshot changes, so the retry cannot
    // wait for the next sync — it must be re-armed by the failure itself.
    await vi.advanceTimersByTimeAsync(ASK_SKIP_TIMEOUT_MS)
    expect(respondApproval).toHaveBeenCalledTimes(2)
  })
})
