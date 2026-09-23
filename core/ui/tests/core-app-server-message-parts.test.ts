import { describe, expect, it } from 'vitest'
import { normalizeAnswerText, projectAssistantMessageParts } from '../src/appServer/messageParts'
import type { MessagePart } from '../src/types'

function part(id: string, partType: MessagePart['partType'], content = '', extra: Partial<MessagePart> = {}): MessagePart {
  return { id, partType, status: 'completed', content, ...extra }
}

describe('assistant message parts projection', () => {
  it('removes the duplicated terminal model text from the process timeline', () => {
    const result = projectAssistantMessageParts([
      part('reasoning', 'reasoning', '先检查文件'),
      part('tool', 'tool_call', '', { toolName: 'read_file' }),
      part('answer-part', 'model_text', '最终答案'),
    ], '最终答案')

    expect(result.processParts.map(item => item.id)).toEqual(['reasoning', 'tool'])
    expect(result.answerPart?.id).toBe('answer-part')
    expect(result.answerText).toBe('最终答案')
  })

  it('normalizes CRLF/LF differences while comparing the answer', () => {
    const result = projectAssistantMessageParts([
      part('answer-part', 'model_text', 'foo\nbar'),
    ], 'foo\r\nbar')

    expect(normalizeAnswerText(' foo\r\nbar ')).toBe('foo\nbar')
    expect(result.answerPart?.id).toBe('answer-part')
    expect(result.processParts).toHaveLength(0)
  })

  it('keeps intermediate model text in the process timeline', () => {
    const result = projectAssistantMessageParts([
      part('intermediate', 'model_text', '先检查文件'),
      part('tool', 'tool_call', '', { toolName: 'read_file' }),
      part('answer-part', 'model_text', '最终答案'),
    ], '最终答案')

    expect(result.processParts.map(item => item.id)).toEqual(['intermediate', 'tool'])
    expect(result.processParts[0].content).toBe('先检查文件')
    expect(result.answerText).toBe('最终答案')
  })

  it('leaves the process timeline unchanged when there is no final answer', () => {
    const parts = [
      part('reasoning', 'reasoning', '思考中'),
      part('tool', 'tool_call', '', { toolName: 'read_file' }),
    ]
    const result = projectAssistantMessageParts(parts, '')

    expect(result.processParts).toEqual(parts)
    expect(result.answerPart).toBeNull()
    expect(result.answerText).toBe('')
  })

  it('uses explicit final markers even when the flat content is stale', () => {
    const result = projectAssistantMessageParts([
      part('final', 'model_text', 'new answer', { metadata: { final: true } }),
    ], 'old snapshot')

    expect(result.answerPart?.id).toBe('final')
    expect(result.processParts).toHaveLength(0)
    expect(result.answerText).toBe('old snapshot')
  })

  it('keeps explicitly intermediate model text in process, including when it matches flat content', () => {
    const intermediate = part('intermediate', 'model_text', '先检查文件', {
      metadata: { final_response: false, has_tool_calls: true },
    })
    for (const live of [false, true]) {
      const result = projectAssistantMessageParts([intermediate], '先检查文件', { live })
      expect(result.processParts).toEqual([intermediate])
      expect(result.answerPart).toBeNull()
      expect(result.answerText).toBe('')
    }
  })

  it('promotes an explicitly final response after an intermediate response', () => {
    const result = projectAssistantMessageParts([
      part('intermediate', 'model_text', '先检查文件', { metadata: { final_response: false, has_tool_calls: true } }),
      part('tool', 'tool_call', '', { toolName: 'read_file' }),
      part('final', 'model_text', '完成', { metadata: { final_response: true, has_tool_calls: false } }),
    ], '完成')
    expect(result.processParts.map(part => part.id)).toEqual(['intermediate', 'tool'])
    expect(result.answerPart?.id).toBe('final')
    expect(result.answerText).toBe('完成')
  })

  it('uses a terminal live model text while the flat content catches up', () => {
    const result = projectAssistantMessageParts([
      part('live-answer', 'model_text', '流式答案'),
    ], '', { live: true })

    expect(result.answerPart?.id).toBe('live-answer')
    expect(result.answerText).toBe('流式答案')
    expect(result.processParts).toHaveLength(0)
  })

  it('does not repeat stale flat content after a later process part arrives', () => {
    const result = projectAssistantMessageParts([
      part('intermediate', 'model_text', '先检查文件'),
      part('tool', 'tool_call', '', { toolName: 'read_file' }),
    ], '先检查文件', { live: true })

    expect(result.processParts.map(item => item.id)).toEqual(['intermediate', 'tool'])
    expect(result.answerPart).toBeNull()
    expect(result.answerText).toBe('')
  })
})
