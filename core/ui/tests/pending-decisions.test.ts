import { describe, expect, it } from 'vitest'
import {
  coreDecisionOptionResponse,
  coreDecisionOptions,
  coreDecisionSubject,
  coreDecisionTitle,
  selectPendingCoreDecisions,
} from '../src/appServer'
import type { CoreMessage, MessagePart } from '../src/types'

const APPROVAL_OPTIONS = [
  { id: 'approve', label: '批准执行', description: '允许后端继续执行这个工具调用。', response: 'approve' },
  { id: 'deny', label: '拒绝执行', description: '不执行这个工具调用，本轮停在等待点。', response: 'deny' },
]

/**
 * A decision part shaped like the real projection of
 * `runtime.approval_request` → `serverRequest` → `decision` part: the runtime's
 * ask sentence lives in `metadata.message`, the choices in `metadata.options`,
 * and the permission facts in `metadata.approval`.
 */
function approvalPart(overrides: Partial<MessagePart> = {}): MessagePart {
  const message = '需要授权后才能执行命令：npm test'
  const { metadata: metadataOverride, ...rest } = overrides
  return {
    id: 'approval-1',
    partType: 'decision',
    status: 'pending',
    content: message,
    label: 'approval',
    toolName: 'run_command',
    toolArgs: { options: APPROVAL_OPTIONS },
    ...rest,
    metadata: {
      message,
      tool_name: 'run_command',
      options: APPROVAL_OPTIONS,
      request_id: 'req-1',
      approval: { tier: 'full_edit', reason: 'requires approval', requires_approval: true, outside_workdir: false },
      waitingRequest: { kind: 'permission', request_id: 'req-1', options: APPROVAL_OPTIONS },
      ...(metadataOverride ?? {}),
    },
  } as MessagePart
}

function questionPart(overrides: Partial<MessagePart> = {}): MessagePart {
  return {
    id: 'question-1',
    partType: 'decision',
    status: 'pending',
    content: '用哪种方式继续？',
    label: 'approval',
    toolName: 'question',
    toolArgs: {
      options: [
        { id: 'A', label: '先做后端', description: '先把接口做通', response: '先做后端' },
        { id: 'B', label: '先做前端', description: '先看界面效果', response: '先做前端' },
      ],
    },
    metadata: {
      message: '用哪种方式继续？',
      tool_name: 'question',
      request_id: 'req-q',
      options: [
        { id: 'A', label: '先做后端', description: '先把接口做通', response: '先做后端' },
        { id: 'B', label: '先做前端', description: '先看界面效果', response: '先做前端' },
      ],
      approval: { tier: 'read_only', reason: 'question', requires_approval: true, outside_workdir: false },
      waitingRequest: { kind: 'permission', request_id: 'req-q' },
    },
    ...overrides,
  } as MessagePart
}

function assistantMessage(id: string, parts: MessagePart[]): CoreMessage {
  return { id, role: 'assistant', content: '', timestamp: '2026-09-28T00:00:00Z', parts }
}

describe('selectPendingCoreDecisions', () => {
  it('reports a waiting approval with its ask, facts and every option', () => {
    const decisions = selectPendingCoreDecisions([assistantMessage('a1', [approvalPart()])])

    expect(decisions).toHaveLength(1)
    const [decision] = decisions
    expect(decision.partId).toBe('approval-1')
    expect(decision.requestId).toBe('req-1')
    expect(decision.subject).toBe('需要授权后才能执行命令：npm test')
    expect(decision.kindLabel).toBe('审批')
    expect(decision.status).toBe('pending')
    expect(decision.submitting).toBe(false)
    expect(decision.canGuide).toBe(true)
    expect(decision.options.map(option => option.label)).toEqual(['批准执行', '拒绝执行'])
    // Facts name the concrete target and the project boundary.
    expect(decision.facts).toEqual([
      { label: '命令', value: 'npm test', tone: 'neutral', mono: true },
      { label: '工具', value: 'run_command', tone: 'neutral', mono: true },
      { label: '范围', value: '项目目录内', tone: 'neutral' },
    ])
  })

  it('does not repeat the ask sentence as its own detail line', () => {
    const decisions = selectPendingCoreDecisions([assistantMessage('a1', [approvalPart()])])
    expect(decisions[0].detail).toBe('')
  })

  it('keeps a supplemental detail line when it says something new', () => {
    const part = approvalPart({ content: '需要授权后才能执行命令：npm test' })
    part.metadata = { ...part.metadata, description: '该命令会重写测试快照。' }
    const decisions = selectPendingCoreDecisions([assistantMessage('a1', [part])])
    expect(decisions[0].detail).toBe('该命令会重写测试快照。')
  })

  it('flags an ask that would act outside the project directory', () => {
    const part = approvalPart({
      metadata: { approval: { tier: 'full_edit', reason: 'outside', requires_approval: true, outside_workdir: true } },
    })
    const decisions = selectPendingCoreDecisions([assistantMessage('a1', [part])])
    expect(decisions[0].facts).toContainEqual({ label: '范围', value: '项目目录之外', tone: 'warn' })
  })

  it('labels a question tool as a question and keeps its own choices', () => {
    const decisions = selectPendingCoreDecisions([assistantMessage('a1', [questionPart()])])

    expect(decisions).toHaveLength(1)
    expect(decisions[0].isQuestion).toBe(true)
    expect(decisions[0].kindLabel).toBe('提问')
    expect(decisions[0].subject).toBe('用哪种方式继续？')
    expect(decisions[0].options.map(option => option.label)).toEqual(['先做后端', '先做前端'])
    // A question has no permission scope to report.
    expect(decisions[0].facts).toEqual([])
  })

  it('excludes answered and non-decision parts', () => {
    const answered = approvalPart({
      id: 'approval-answered',
      status: 'completed',
      metadata: {
        waitingRequest: { request_id: 'req-1', response: { action: 'approve', response: 'approve_once' } },
      },
    })
    const answeredByMetadata = approvalPart({
      id: 'approval-waiting-response',
      status: 'pending',
      metadata: { waitingResponse: { action: 'deny', response: 'deny' } },
    })
    const toolPart: MessagePart = {
      id: 'tool-1',
      partType: 'tool_call',
      status: 'pending',
      content: 'not a decision',
    }
    const decisions = selectPendingCoreDecisions([
      assistantMessage('a1', [answered, answeredByMetadata, toolPart]),
    ])

    expect(decisions).toEqual([])
  })

  it('keeps a submitted decision visible as submitting until it resolves', () => {
    const submitting = approvalPart({ id: 'approval-running', status: 'running' })
    const decisions = selectPendingCoreDecisions([assistantMessage('a1', [submitting])])

    expect(decisions).toHaveLength(1)
    expect(decisions[0].submitting).toBe(true)
    // Guidance cannot be sent twice for the same request.
    expect(decisions[0].canGuide).toBe(false)
  })

  it('marks a pending decision submitting from the approval controller set', () => {
    const decisions = selectPendingCoreDecisions(
      [assistantMessage('a1', [approvalPart()])],
      { submittingRequestIds: new Set(['req-1']) },
    )
    expect(decisions[0].submitting).toBe(true)
  })

  it('queues several waiting requests oldest first, across messages and sub-agents', () => {
    const first = approvalPart({ id: 'approval-first', metadata: { request_id: 'req-1', message: '第一个请求' } })
    const second = questionPart({ id: 'question-second' })
    const nested = approvalPart({ id: 'approval-nested', metadata: { request_id: 'req-nested', message: '子代理请求' } })
    const nestedContainer: MessagePart = {
      id: 'sub-agent-1',
      partType: 'agent_summary',
      status: 'pending',
      content: '',
      metadata: { subLineParts: [nested] },
    }
    const decisions = selectPendingCoreDecisions([
      assistantMessage('a1', [first]),
      { id: 'u1', role: 'user', content: 'go', timestamp: '2026-09-28T00:00:01Z', parts: [] },
      assistantMessage('a2', [second, nestedContainer]),
    ])

    expect(decisions.map(decision => decision.partId)).toEqual([
      'approval-first',
      'question-second',
      'approval-nested',
    ])
    expect(decisions.map(decision => decision.submitting)).toEqual([false, false, false])
  })

  it('projects every option through the same wire response the in-thread card sends', () => {
    const part = approvalPart()
    const decisions = selectPendingCoreDecisions([assistantMessage('a1', [part])])

    expect(decisions[0].options.map(option => option.wireResponse)).toEqual(['approve', 'deny'])
    for (const option of coreDecisionOptions(part)) {
      expect(decisions[0].options.find(item => item.id === option.id)?.wireResponse)
        .toBe(coreDecisionOptionResponse(part, option))
    }
  })

  it('answers without a runtime response field by describing the choice', () => {
    const part = approvalPart({
      toolArgs: { options: [{ id: 'plan-b', label: '改用方案 B', description: '更保守' }] },
      metadata: { message: '选哪个方案？', options: undefined },
    })
    const decisions = selectPendingCoreDecisions([assistantMessage('a1', [part])])

    expect(decisions[0].options[0].wireResponse).toBe('我选择：改用方案 B\n原因/说明：更保守\n对应决策：选哪个方案？')
  })

  it('scans each message only once for an unchanged message object', () => {
    let partsReads = 0
    const parts = [approvalPart()]
    const message = assistantMessage('a1', parts)
    Object.defineProperty(message, 'parts', {
      get() {
        partsReads += 1
        return parts
      },
      enumerable: true,
      configurable: true,
    })

    expect(selectPendingCoreDecisions([message])).toHaveLength(1)
    expect(selectPendingCoreDecisions([message])).toHaveLength(1)
    expect(partsReads).toBe(1)
  })

  it('keeps the in-thread card label and subject on their own contracts', () => {
    // The card keeps its historical label chain; the answering surface names
    // the request the runtime actually wrote.
    const part = approvalPart()
    expect(coreDecisionTitle(part)).toBe('需要确认：approval')
    expect(coreDecisionSubject(part)).toBe('需要授权后才能执行命令：npm test')
    expect(coreDecisionSubject(part, 12)).toBe('需要授权后才能执行命令：...')
  })
})
