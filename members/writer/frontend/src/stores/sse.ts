// ============================================================
// SSE Store — manages streaming connection to Writer backend
// ============================================================

import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '@/api'
import { readSSEStream } from '@/composables/useSSE'
import { useSessionStore } from './session'
import { useStepStore } from './step'
import type { ChatRequest, ReplyAttachment, SSEEvent, Message, SSEWriterProgress, Step } from '@/types'
import type { RuntimeActivityGroup, RuntimeActivityStatus, RuntimeDisplayGroup, RuntimeActivity } from '@/lib/sse'
export type { RuntimeActivity, RuntimeActivityGroup, RuntimeActivityStatus, RuntimeDisplayGroup }
import {
  businessStatusText,
  phaseStatusText,
  workflowStatusText,
  planProgressStatusText,
  verificationStatusText,
  loopPositionStatusText,
  groupLabel,
  visibleActivityText,
  activityStatus,
  activityDisplayGroup,
  activityTag,
  stepActivityGroup,
  stepActivityLabel,
  stepActivityDetail,
  phaseActivityGroup,
  gitActivityLabel,
  gitActivityDetail,
  normalizeReplyText,
  extractReplyAttachments,
  mergeReplyAttachments,
  decisionMessageId,
} from '@/lib/sse'

export const useSseStore = defineStore('sse', () => {
  // --- State ---

  const running = ref(false)
  const awaitingUser = ref(false)
  const statusText = ref('')
  const assistantDraft = ref('')
  const assistantDraftAttachments = ref<ReplyAttachment[]>([])
  const lastEventAt = ref<string | null>(null)
  const latestProgress = ref<SSEWriterProgress | null>(null)
  const gitRefreshTick = ref(0)
  const lastGitEventAt = ref<string | null>(null)
  const lastGitSessionId = ref<string | null>(null)
  const latestLifecycleAlert = ref<{
    session_id: string
    lifecycle_type: 'failed' | 'error'
    reason: string
    details: Record<string, unknown>
    created_at: string
  } | null>(null)
  const activityFeed = ref<RuntimeActivity[]>([])
  const activeActivityGroup = ref<RuntimeActivityGroup | null>(null)
  const eventCount = ref(0)
  const llmCallCount = ref(0)
  let activitySeq = 0
  let controller: AbortController | null = null
  let eventController: AbortController | null = null
  let watchedSessionId: string | null = null

  // --- Actions ---

  /**
   * Start an SSE stream for the given session.
   * Calls api.chat() to get a Response stream, then reads SSE events.
   */
  async function startStream(sessionId: string, chatRequest: ChatRequest) {
    // Stop any existing stream
    stopStream()

    running.value = true
    awaitingUser.value = false
    statusText.value = '正在启动'
    assistantDraft.value = ''
    assistantDraftAttachments.value = []
    latestProgress.value = null
    latestLifecycleAlert.value = null
    activityFeed.value = []
    activeActivityGroup.value = 'plan'
    addActivity(sessionId, 'plan', '接收任务', '正在建立运行流。', 'running')
    eventCount.value = 0
    llmCallCount.value = 0

    const activeController = new AbortController()
    controller = activeController

    try {
      const response = await api.chat(sessionId, chatRequest, activeController.signal)

      if (!response.ok) {
        running.value = false
        statusText.value = `请求失败：HTTP ${response.status}`
        return
      }

      const stream = response.body
      if (!stream) {
        running.value = false
        statusText.value = '后端没有返回运行流'
        return
      }

      await readSSEStream(
        stream,
        (event: SSEEvent) => {
          handleEvent(sessionId, event)
        },
        activeController.signal,
      )
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // User cancelled — expected
        statusText.value = '已取消'
      } else {
        statusText.value = `运行出错：${err instanceof Error ? err.message : String(err)}`
      }
    } finally {
      running.value = false
      if (controller === activeController) controller = null
    }
  }

  async function watchSessionEvents(sessionId: string) {
    if (watchedSessionId === sessionId && eventController) return
    stopSessionEvents()
    watchedSessionId = sessionId
    const activeController = new AbortController()
    eventController = activeController

    try {
      const response = await api.sessionEvents(sessionId, activeController.signal)
      if (!response.ok || !response.body) return
      await readSSEStream(
        response.body,
        (event: SSEEvent) => {
          handleEvent(sessionId, event)
        },
        activeController.signal,
      )
    } catch (err: unknown) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        statusText.value = `事件流出错：${err instanceof Error ? err.message : String(err)}`
      }
    } finally {
      if (eventController === activeController) {
        eventController = null
        watchedSessionId = null
      }
    }
  }

  function stopSessionEvents() {
    if (eventController) {
      eventController.abort()
      eventController = null
    }
    watchedSessionId = null
  }

  /**
   * Stop the active SSE stream.
   */
  function stopStream() {
    if (controller) {
      controller.abort()
      controller = null
    }
    running.value = false
  }

  /**
   * Handle a parsed SSE event and update relevant stores.
   */
  function handleEvent(sessionId: string, event: SSEEvent) {
    lastEventAt.value = new Date().toISOString()
    eventCount.value += 1

    const sessionStore = useSessionStore()
    const stepStore = useStepStore()

    switch (event.event) {
      case 'writer_step': {
        const step = event.step
        stepStore.upsertStep(step)
        statusText.value = `步骤：${businessStatusText(step.step_type || '处理中')}（${businessStatusText(step.status || '')}）`
        addStepActivity(sessionId, step)
        break
      }

      case 'writer_message':
        if (event.message) {
          sessionStore.upsertMessage(event.message)
        }
        break

      case 'writer_progress':
        latestProgress.value = event
        if (event.loop_position === 'llm_call_started') {
          llmCallCount.value += 1
        }
        if ((event.phase && event.phase !== 'planning') || event.workflow) {
          awaitingUser.value = false
        }
        statusText.value = event.workflow
          ? workflowStatusText(event.workflow)
          : event.phase
            ? phaseStatusText(event.phase)
            : event.plan_progress
              ? planProgressStatusText(event.plan_progress)
              : event.verification
                ? verificationStatusText(event.verification)
                : event.loop_position
                  ? loopPositionStatusText(event.loop_position)
                  : '处理中'
        addProgressActivity(sessionId, event)
        break

      case 'writer_response':
        if (event.output_type === 'reply') {
          const replyText = normalizeReplyText(event)
          assistantDraftAttachments.value = mergeReplyAttachments(
            assistantDraftAttachments.value,
            extractReplyAttachments(event.output_meta),
          )
          if (replyText) {
            if (event.output_meta?.final === true) {
              assistantDraft.value = replyText
            } else {
              assistantDraft.value += assistantDraft.value ? `\n${replyText}` : replyText
            }
            addActivity(sessionId, 'reply', '正在组织回复', replyText, 'running')
          }
        } else if (event.output_type === 'thought') {
          const thoughtText = event.text || '正在整理下一步。'
          statusText.value = businessStatusText(thoughtText)
          addActivity(sessionId, 'plan', 'LLM 过程', thoughtText, 'running')
        } else if (event.text) {
          statusText.value = businessStatusText(event.text)
          addActivity(sessionId, 'plan', 'LLM 过程', event.text, 'running')
        }
        statusText.value = event.output_type === 'reply' ? '正在回复' : statusText.value
        break

      case 'writer_decision': {
        if (event.decision_type === 'waiting_for_user' || event.decision_type === 'plan_ready' || event.decision_type === 'decision_point') {
          awaitingUser.value = true
          statusText.value = event.title || '等待用户决策'
          addActivity(sessionId, 'decision', event.title || '等待用户决策', '需要确认后继续。', 'waiting')

          const options = event.options && event.options.length > 0
            ? event.options
            : [{ id: 'confirm', label: '确认并继续执行', description: '继续当前任务。' }]
          if (event.decision_type === 'waiting_for_user' && hasActiveDecisionMessage(sessionStore, sessionId)) {
            mergeActiveDecisionContext(sessionStore, sessionId, {
              question: event.title || '',
              waiting_title: event.title || '',
            })
            break
          }
          const decisionMsg: Message = {
            id: decisionMessageId(sessionId, event),
            session_id: sessionId,
            role: 'assistant',
            content: event.title || 'Writer 需要你的决策',
            parts: { decision: { ...event, options } },
            created_at: new Date().toISOString(),
          }
          sessionStore.upsertMessage(decisionMsg)
        }
        break
      }

      case 'writer_git':
        gitRefreshTick.value += 1
        lastGitEventAt.value = new Date().toISOString()
        lastGitSessionId.value = sessionId
        statusText.value = event.git_type ? `Git：${businessStatusText(event.git_type)}` : '暂无 Git 状态'
        addActivity(sessionId, 'git', gitActivityLabel(event.git_type), gitActivityDetail(event.data), 'running')
        break

      case 'writer_lifecycle': {
        switch (event.lifecycle_type) {
          case 'done':
            running.value = false
            awaitingUser.value = false
            statusText.value = '已完成'
            finishRunningActivities(sessionId, 'done')
            addActivity(sessionId, 'system', '任务完成', '过程已折叠，可查看最终回复和改动。', 'done')
            break
          case 'failed':
            running.value = false
            awaitingUser.value = false
            statusText.value = event.reason ? businessStatusText(event.reason) : '失败'
            finishRunningActivities(sessionId, 'failed')
            addActivity(sessionId, 'system', '任务失败', businessStatusText(event.reason || '失败'), 'failed')
            recordLifecycleAlert(sessionId, 'failed', event.reason || '', event.details || {})
            break
          case 'error':
            running.value = false
            awaitingUser.value = false
            statusText.value = event.reason ? businessStatusText(event.reason) : '出错'
            finishRunningActivities(sessionId, 'failed')
            addActivity(sessionId, 'system', '运行出错', businessStatusText(event.reason || '出错'), 'failed')
            recordLifecycleAlert(sessionId, 'error', event.reason || '', event.details || {})
            break
          case 'cancelled':
            running.value = false
            awaitingUser.value = false
            statusText.value = '已取消'
            finishRunningActivities(sessionId, 'done')
            addActivity(sessionId, 'system', '已停止', '用户已停止本轮任务。', 'done')
            break
          case 'resumed':
            awaitingUser.value = false
            statusText.value = '继续执行'
            addActivity(sessionId, 'system', '继续执行', '已从暂停点恢复。', 'running')
            break
        }
        break
      }

      // Legacy event backward compatibility
      case 'writer_done':
        running.value = false
        awaitingUser.value = false
        statusText.value = '已完成'
        finishRunningActivities(sessionId, 'done')
        addActivity(sessionId, 'system', '任务完成', '过程已折叠，可查看最终回复和改动。', 'done')
        break

      case 'writer_failed':
        running.value = false
        awaitingUser.value = false
        statusText.value = event.reason ? businessStatusText(event.reason) : '失败'
        finishRunningActivities(sessionId, 'failed')
        addActivity(sessionId, 'system', '任务失败', businessStatusText(event.reason || '失败'), 'failed')
        recordLifecycleAlert(sessionId, 'failed', event.reason || '', {})
        break

      case 'writer_error':
        running.value = false
        awaitingUser.value = false
        statusText.value = event.error || event.message ? businessStatusText(event.error || event.message || '') : '出错'
        finishRunningActivities(sessionId, 'failed')
        addActivity(sessionId, 'system', '运行出错', businessStatusText(event.error || event.message || '出错'), 'failed')
        recordLifecycleAlert(sessionId, 'error', event.error || event.message || '', {})
        break

      case 'writer_waiting_for_user':
        awaitingUser.value = true
        statusText.value = event.question || '等待用户输入'
        addActivity(sessionId, 'decision', event.question || '等待用户输入', '需要用户补充后继续。', 'waiting')
        break

      case 'writer_resumed':
        awaitingUser.value = false
        statusText.value = '继续执行'
        addActivity(sessionId, 'system', '继续执行', '已从暂停点恢复。', 'running')
        break

      case 'writer_agent_started':
        statusText.value = `Agent：${event.agent_name || '处理中'}`
        addActivity(sessionId, 'agent', `Agent：${event.agent_name || '处理中'}`, event.task || '正在分派子任务。', 'running')
        break

      case 'writer_agent_progress':
        statusText.value = event.phase ? `Agent：${businessStatusText(event.phase)}` : 'Agent 处理中'
        addActivity(sessionId, 'agent', event.phase ? `Agent：${businessStatusText(event.phase)}` : 'Agent 处理中', event.detail || '子任务正在推进。', 'running')
        break

      case 'writer_agent_completed':
        statusText.value = event.status === 'failed' || event.status === 'error'
          ? 'Agent 失败'
          : 'Agent 已完成'
        addActivity(
          sessionId,
          'agent',
          event.status === 'failed' || event.status === 'error' ? 'Agent 失败' : 'Agent 已完成',
          '',
          event.status === 'failed' || event.status === 'error' ? 'failed' : 'done',
        )
        break
    }
  }

  function addActivity(
    sessionId: string,
    group: RuntimeActivityGroup,
    label: string,
    detail = '',
    status: RuntimeActivityStatus = 'running',
  ) {
    const cleanLabel = visibleActivityText(label) || groupLabel(group)
    const cleanDetail = visibleActivityText(detail)
    const rawLabel = String(label || '').trim()
    const rawDetail = String(detail || '').trim()
    const last = activityFeed.value[activityFeed.value.length - 1]
    if (
      last
      && last.session_id === sessionId
      && last.group === group
      && last.label === cleanLabel
      && last.detail === cleanDetail
      && last.status === status
    ) {
      return
    }
    activeActivityGroup.value = group
    activitySeq += 1
    activityFeed.value.push({
      id: `activity-${Date.now()}-${activitySeq}`,
      session_id: sessionId,
      group,
      display_group: activityDisplayGroup(group, status),
      tag: activityTag(group, cleanLabel, status),
      label: cleanLabel,
      detail: cleanDetail,
      raw_label: rawLabel,
      raw_detail: rawDetail,
      status,
      at: new Date().toISOString(),
    })
    if (activityFeed.value.length > 500) {
      activityFeed.value = activityFeed.value.slice(-500)
    }
  }

  function addStepActivity(sessionId: string, step: Step) {
    const group = stepActivityGroup(step)
    const label = stepActivityLabel(step, group)
    const detail = stepActivityDetail(step)
    const status = activityStatus(step.status)
    addActivity(sessionId, group, label, detail, status)
  }

  function addProgressActivity(sessionId: string, event: SSEWriterProgress) {
    if (event.workflow) {
      addActivity(sessionId, 'agent', workflowStatusText(event.workflow), '工作流阶段已推进。', 'running')
      return
    }
    if (event.plan_progress) {
      addActivity(sessionId, 'plan', planProgressStatusText(event.plan_progress), event.plan_progress.current_step || event.plan_progress.next_step || '', 'running')
      return
    }
    if (event.verification) {
      addActivity(sessionId, 'verify', verificationStatusText(event.verification), event.verification.summary || '', event.verification.passed === false ? 'failed' : event.verification.passed === true ? 'done' : 'running')
      return
    }
    if (event.loop_position) {
      addActivity(sessionId, 'plan', loopPositionStatusText(event.loop_position), '', event.loop_position === 'llm_call_completed' ? 'done' : 'running')
      return
    }
    if (event.mode) {
      addActivity(sessionId, 'plan', `切换模式：${businessStatusText(event.mode)}`, '', 'running')
      return
    }
    if (event.phase) {
      addActivity(sessionId, phaseActivityGroup(event.phase), phaseStatusText(event.phase), '', event.phase === 'completed' ? 'done' : event.phase === 'error' ? 'failed' : 'running')
    }
  }

  function finishRunningActivities(sessionId: string, status: 'done' | 'failed') {
    activityFeed.value = activityFeed.value.map((item) => (
      item.session_id === sessionId && item.status === 'running'
        ? { ...item, status }
        : item
    ))
  }

  function recordLifecycleAlert(
    sessionId: string,
    lifecycleType: 'failed' | 'error',
    reason = '',
    details: Record<string, unknown> = {},
  ) {
    latestLifecycleAlert.value = {
      session_id: sessionId,
      lifecycle_type: lifecycleType,
      reason,
      details,
      created_at: new Date().toISOString(),
    }
    upsertLifecycleMessage(sessionId, lifecycleType, reason, details, latestLifecycleAlert.value.created_at)
  }

  function replayLifecycleAlert(sessionId: string) {
    const alert = latestLifecycleAlert.value
    if (!alert || alert.session_id !== sessionId) return
    upsertLifecycleMessage(alert.session_id, alert.lifecycle_type, alert.reason, alert.details, alert.created_at)
  }

  return {
    running,
    awaitingUser,
    statusText,
    assistantDraft,
    assistantDraftAttachments,
    lastEventAt,
    latestProgress,
    gitRefreshTick,
    lastGitEventAt,
    lastGitSessionId,
    latestLifecycleAlert,
    activityFeed,
    activeActivityGroup,
    eventCount,
    llmCallCount,
    startStream,
    stopStream,
    watchSessionEvents,
    stopSessionEvents,
    handleEvent,
    replayLifecycleAlert,
  }
})

function hasActiveDecisionMessage(sessionStore: ReturnType<typeof useSessionStore>, sessionId: string): boolean {
  return sessionStore.messages.some((message) => {
    if (message.session_id !== sessionId || message.role !== 'assistant') return false
    const parts = message.parts as { decision?: { decision_type?: string } } | null
    const type = parts?.decision?.decision_type || ''
    return type === 'plan_ready' || type === 'decision_point'
  })
}

function mergeActiveDecisionContext(
  sessionStore: ReturnType<typeof useSessionStore>,
  sessionId: string,
  patch: Record<string, unknown>,
) {
  const message = [...sessionStore.messages].reverse().find((item) => {
    if (item.session_id !== sessionId || item.role !== 'assistant') return false
    const parts = item.parts as { decision?: { decision_type?: string; context?: Record<string, unknown> } } | null
    const type = parts?.decision?.decision_type || ''
    return type === 'plan_ready' || type === 'decision_point'
  })
  if (!message) return
  const parts = (message.parts || {}) as Record<string, unknown>
  const decision = (parts.decision || {}) as Record<string, unknown>
  const context = (decision.context || {}) as Record<string, unknown>
  sessionStore.upsertMessage({
    ...message,
    parts: {
      ...parts,
      decision: {
        ...decision,
        context: {
          ...context,
          ...Object.fromEntries(Object.entries(patch).filter(([, value]) => String(value || '').trim())),
        },
      },
    },
  })
}

function upsertLifecycleMessage(
  sessionId: string,
  lifecycleType: 'failed' | 'error',
  reason = '',
  details: Record<string, unknown> = {},
  createdAt = new Date().toISOString(),
) {
  const sessionStore = useSessionStore()
  const title = lifecycleType === 'failed' ? 'Writer 执行失败' : 'Writer 运行出错'
  const message: Message = {
    id: `local-lifecycle-${sessionId}-${lifecycleType}`,
    session_id: sessionId,
    role: 'assistant',
    content: title,
    parts: {
      lifecycle: {
        lifecycle_type: lifecycleType,
        reason,
        details,
      },
    },
    created_at: createdAt,
  }
  sessionStore.upsertMessage(message)
}
