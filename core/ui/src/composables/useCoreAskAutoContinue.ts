import { onScopeDispose, watch, type Ref } from 'vue'
import {
  coreDecisionIsQuestion,
  coreDecisionIsUnanswered,
  coreDecisionRequestId,
} from '../appServer/pendingDecisions'
import type { CoreMessage } from '../types'

/**
 * 无人回答的等待窗口：提问卡超过它仍未答复，就按「用户跳过」回传，本轮继续。
 *
 * 只处理**提问卡**（`question` 工具的提问）。权限审批卡是安全边界，超时不代表
 * 同意——自动放行待审批操作是这次明确不要的行为，所以审批卡会一直等下去。
 */
export const ASK_SKIP_TIMEOUT_MS = 5 * 60 * 1000

/**
 * 回传给模型的“用户跳过”。答案文本自身说明来源，记录里不会像用户选的；
 * 措辞与「无用户输入」的既有约定一致（未收集到用户答案），模型据此换问法或
 * 按合理默认继续。
 */
export const ASK_SKIP_GUIDANCE = '用户跳过回答：等待 5 分钟未响应，未收集到用户答案。'

export interface UseCoreAskAutoContinueOptions {
  messages: Readonly<Ref<CoreMessage[]>>
  /** 读取「提问自动继续」偏好；在出现待答复提问卡时才问，避免每帧一次 RPC。 */
  loadEnabled(): Promise<boolean>
  respondApproval(requestId: string, decision: string, guidance: string): Promise<void>
  onAutoSkipped?(requestId: string): void
  onError?(message: string): void
  timeoutMs?: number
}

export function useCoreAskAutoContinue(options: UseCoreAskAutoContinueOptions) {
  const timeoutMs = options.timeoutMs ?? ASK_SKIP_TIMEOUT_MS
  const timers = new Map<string, ReturnType<typeof setTimeout>>()
  /** 已经答复过（手动或自动）的请求，不再重新计时。 */
  const settled = new Set<string>()
  /** 已经读过偏好的请求：偏好为关时不必每帧重问。 */
  const checked = new Set<string>()
  const arming = new Set<string>()

  function pendingQuestionIds(): Set<string> {
    const ids = new Set<string>()
    for (const message of options.messages.value || []) {
      if (message.role !== 'assistant') continue
      for (const part of message.parts || []) {
        if (part.partType !== 'decision') continue
        // 审批卡永远不自动处理：只有提问卡走这条自动路径。
        if (!coreDecisionIsQuestion(part)) continue
        if (!coreDecisionIsUnanswered(part)) continue
        const id = coreDecisionRequestId(part)
        if (id) ids.add(id)
      }
    }
    return ids
  }

  function clearTimer(requestId: string) {
    const timer = timers.get(requestId)
    if (timer !== undefined) {
      clearTimeout(timer)
      timers.delete(requestId)
    }
  }

  function schedule(requestId: string) {
    if (timers.has(requestId) || settled.has(requestId)) return
    timers.set(requestId, setTimeout(() => { void fire(requestId) }, timeoutMs))
  }

  function syncPendingQuestions() {
    const pending = pendingQuestionIds()
    for (const requestId of [...timers.keys()]) {
      if (!pending.has(requestId)) clearTimer(requestId)
    }
    for (const requestId of pending) {
      if (timers.has(requestId) || settled.has(requestId) || checked.has(requestId)) continue
      void arm(requestId)
    }
  }

  async function arm(requestId: string) {
    if (arming.has(requestId)) return
    arming.add(requestId)
    try {
      if (!(await options.loadEnabled())) {
        checked.add(requestId)
        return
      }
      if (!pendingQuestionIds().has(requestId)) return
      schedule(requestId)
    } catch (error) {
      // 读不到偏好就什么都不做：宁可继续等，也不要凭空替用户跳过。
      checked.add(requestId)
      options.onError?.(error instanceof Error ? error.message : String(error))
    } finally {
      arming.delete(requestId)
    }
  }

  async function fire(requestId: string) {
    clearTimer(requestId)
    if (!pendingQuestionIds().has(requestId)) return
    settled.add(requestId)
    try {
      // 提问的答复走 other_guidance：把「用户跳过」当答案文本回传，模型可以据此
      // 换个问法或按合理默认继续；这不是选项里的任何一个选择。
      await options.respondApproval(requestId, 'other_guidance', ASK_SKIP_GUIDANCE)
      options.onAutoSkipped?.(requestId)
    } catch (error) {
      // 答复失败不算已回答，也不能等下一次同步——挂起中的轮次不会再推快照，
      // 所以这里直接重新计时，等窗口过去再试一次。
      settled.delete(requestId)
      options.onError?.(error instanceof Error ? error.message : String(error))
      if (pendingQuestionIds().has(requestId)) schedule(requestId)
    }
  }

  watch(options.messages, syncPendingQuestions, { immediate: true })
  onScopeDispose(() => {
    for (const requestId of [...timers.keys()]) clearTimer(requestId)
  })

  return {
    syncPendingQuestions,
    /** 已开始计时的提问请求（测试与调试用）。 */
    armedRequestIds: () => [...timers.keys()],
  }
}
