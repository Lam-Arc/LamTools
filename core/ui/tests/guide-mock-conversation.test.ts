import { describe, expect, it } from 'vitest'

import {
  MOCK_USER_TEXT,
  createMockConversation,
  mockAnswerText,
  mockAssistantMessage,
  mockCaption,
  mockUserMessage,
  reduceMockConversation,
} from '../src/guide/mockConversation.ts'

/**
 * user:“可以自动建一个教学示例会话，使用mock数据流演示并走过完整agent流程
 *      （不调用真实API）”+
 * (这个用例守两件事：流程必须真的走得通；拒绝分支必须真的什么都不做。)
 */

describe('guide mock conversation', () => {
  it('walks the full happy path: think, read, ask, write, answer', () => {
    let state = createMockConversation()
    expect(state.stage).toBe('idle')
    expect(mockUserMessage(state)).toBeNull()

    state = reduceMockConversation(state, 'send')
    expect(state.stage).toBe('thinking')
    expect(mockUserMessage(state)?.content).toBe(MOCK_USER_TEXT)

    state = reduceMockConversation(state, 'advance')
    expect(state.stage).toBe('reading')
    state = reduceMockConversation(state, 'advance')
    expect(state.stage).toBe('approval')

    // 审批没答之前，绝不能进入写入阶段。
    expect(mockAssistantMessage(state)?.parts?.some(part => part.id === 'guide-demo-write')).toBe(false)
    expect(mockCaption(state).title).toContain('停下来问你')

    state = reduceMockConversation(state, 'allow-once')
    expect(state.stage).toBe('writing')
    expect(mockAssistantMessage(state)?.parts?.some(part => part.id === 'guide-demo-write')).toBe(true)

    state = reduceMockConversation(state, 'advance')
    expect(state.stage).toBe('answered')
    expect(mockAnswerText(state)).toContain('37')
    expect(mockAnswerText(state)).toContain('没有删任何东西')
    expect(mockAnswerText(state)).toContain('下次同类操作')
  })

  it('treats deny as a real branch that touches nothing', () => {
    let state = createMockConversation()
    state = reduceMockConversation(state, 'send')
    state = reduceMockConversation(state, 'advance')
    state = reduceMockConversation(state, 'advance')
    state = reduceMockConversation(state, 'deny')

    expect(state.stage).toBe('denied')
    const parts = mockAssistantMessage(state)?.parts ?? []
    expect(parts.some(part => part.id === 'guide-demo-write')).toBe(false)
    expect(mockCaption(state).title).toContain('先不要')

    state = reduceMockConversation(state, 'advance')
    expect(mockAnswerText(state)).toContain('一点没改')
  })

  it('remembers a trust choice without skipping the write step', () => {
    let state = createMockConversation()
    state = reduceMockConversation(state, 'send')
    state = reduceMockConversation(state, 'advance')
    state = reduceMockConversation(state, 'advance')
    state = reduceMockConversation(state, 'trust-kind')
    expect(state.trusted).toBe(true)
    state = reduceMockConversation(state, 'advance')
    expect(mockAnswerText(state)).toContain('以后这类都允许')
  })

  it('ignores actions that do not belong to the current stage', () => {
    const idle = createMockConversation()
    expect(reduceMockConversation(idle, 'allow-once').stage).toBe('idle')
    expect(reduceMockConversation(idle, 'advance').stage).toBe('idle')
    const answered = reduceMockConversation(
      reduceMockConversation(createMockConversation(), 'send'),
      'advance',
    )
    expect(answered.stage).toBe('reading')
    expect(reduceMockConversation(answered, 'send').stage).toBe('reading')
  })

  it('shows the decision card only while it is pending, then leaves a visible trace', () => {
    let state = createMockConversation()
    state = reduceMockConversation(state, 'send')
    state = reduceMockConversation(state, 'advance')
    state = reduceMockConversation(state, 'advance')

    const pending = mockAssistantMessage(state)?.parts?.find(part => part.id === 'guide-demo-decision')
    expect(pending?.status).toBe('pending')
    expect(Array.isArray((pending?.toolArgs as Record<string, unknown>)?.options)).toBe(true)

    state = reduceMockConversation(state, 'allow-once')
    const settled = mockAssistantMessage(state)?.parts?.find(part => part.id === 'guide-demo-decision')
    expect(settled?.status).toBe('completed')
    const echo = mockAssistantMessage(state)?.parts?.find(part => part.id === 'guide-demo-choice')
    expect(echo?.content).toBe('允许这一次')
  })

  it('streams the answer without leaking the conclusion early', () => {
    let state = createMockConversation()
    state = reduceMockConversation(state, 'send')
    state = reduceMockConversation(state, 'advance')
    state = reduceMockConversation(state, 'advance')
    state = reduceMockConversation(state, 'allow-once')
    state = reduceMockConversation(state, 'advance')

    const partial = mockAssistantMessage(state, 4)
    expect(partial?.content).toHaveLength(4)
    expect(partial?.content).not.toBe(mockAnswerText(state))
    const full = mockAssistantMessage(state)
    expect(full?.content).toBe(mockAnswerText(state))
  })
})
