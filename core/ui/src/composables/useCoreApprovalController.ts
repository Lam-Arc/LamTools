import { ref, watch, type Ref } from 'vue'
import { coreDecisionSelectionPlan, type CoreDecisionSelectionPayload } from '../appServer/workbenchActions'
import type { CoreMessage, MessagePart } from '../types'

export interface UseCoreApprovalControllerOptions {
  messages: Readonly<Ref<CoreMessage[]>>
  hasActiveThread: Readonly<Ref<boolean>>
  canRespondApproval: Readonly<Ref<boolean>>
  ensureApprovalChannel?(): Promise<boolean>
  respondApproval(requestId: string, decision: string, guidance: string): Promise<void>
  submitText(text: string): Promise<void>
  deferText(text: string): void
}

export type CoreApprovalHandlingResult = 'approval' | 'text' | 'deferred' | 'failed' | 'ignored'

export function useCoreApprovalController(options: UseCoreApprovalControllerOptions) {
  const lastError = ref('')
  const submittingRequestIds = ref(new Set<string>())

  watch(options.messages, clearResolvedSubmissions)

  async function handleDecision(payload: CoreDecisionSelectionPayload): Promise<CoreApprovalHandlingResult> {
    const plan = coreDecisionSelectionPlan(findMessagePart(payload.partId), payload)
    if (plan.status === 'approval') {
      let canRespond = options.canRespondApproval.value
      if (!canRespond && options.ensureApprovalChannel) {
        try {
          canRespond = await options.ensureApprovalChannel()
        } catch (error) {
          lastError.value = error instanceof Error ? error.message : String(error)
          return 'deferred'
        }
      }
      if (!canRespond) {
        lastError.value = 'Approval channel is unavailable'
        return 'deferred'
      }
      if (submittingRequestIds.value.has(plan.requestId)) return 'ignored'
      addSubmittingRequest(plan.requestId)
      try {
        await options.respondApproval(plan.requestId, plan.decision, plan.guidance)
        lastError.value = ''
        return 'approval'
      } catch (error) {
        lastError.value = error instanceof Error ? error.message : String(error)
        removeSubmittingRequest(plan.requestId)
        return 'failed'
      }
    }

    const text = plan.status === 'text' ? plan.text : ''
    if (!text) return 'ignored'
    if (options.hasActiveThread.value) {
      try {
        await options.submitText(text)
        lastError.value = ''
        return 'text'
      } catch (error) {
        lastError.value = error instanceof Error ? error.message : String(error)
        return 'failed'
      }
    }
    options.deferText(text)
    return 'deferred'
  }

  function findMessagePart(partId: string): MessagePart | null {
    for (const message of options.messages.value) {
      const part = messagePartsDeep(message.parts || []).find(item => item.id === partId)
      if (part) return part
    }
    return null
  }

  function addSubmittingRequest(requestId: string) {
    submittingRequestIds.value = new Set([...submittingRequestIds.value, requestId])
  }

  function removeSubmittingRequest(requestId: string) {
    const next = new Set(submittingRequestIds.value)
    next.delete(requestId)
    submittingRequestIds.value = next
  }

  function clearResolvedSubmissions() {
    if (submittingRequestIds.value.size === 0) return
    const waiting = new Set<string>()
    for (const message of options.messages.value) {
      for (const part of messagePartsDeep(message.parts || [])) {
        const request = asRecord(part.metadata?.waitingRequest)
        const requestId = String(request?.request_id || '')
        if (requestId && !request?.response) waiting.add(requestId)
      }
    }
    const next = new Set([...submittingRequestIds.value].filter(requestId => waiting.has(requestId)))
    if (next.size !== submittingRequestIds.value.size) submittingRequestIds.value = next
  }

  return {
    handleDecision,
    lastError,
    submittingRequestIds,
  }
}

function messagePartsDeep(parts: MessagePart[]): MessagePart[] {
  const result: MessagePart[] = []
  const pending = [...parts]
  while (pending.length > 0) {
    const part = pending.shift()
    if (!part) continue
    result.push(part)
    const nested = part.metadata?.subLineParts || part.metadata?.sub_line_parts
    if (!Array.isArray(nested)) continue
    pending.push(...nested.filter(isMessagePart))
  }
  return result
}

function isMessagePart(value: unknown): value is MessagePart {
  return Boolean(value) && typeof value === 'object' && typeof (value as MessagePart).id === 'string'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? value as Record<string, unknown> : null
}
