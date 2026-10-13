import { describe, expect, it } from 'vitest'
import { selectCoreSubAgentRun, selectCoreSubAgentRuns } from '../src/agents/subAgentProjection'
import type { CoreMessage, MessagePart } from '../src/types'

/**
 * 时间线顺序的口径（显式定义，供测试固定）：
 *
 * 1. 一个运行的条目按**来源顺序**排列——主线程里这些行的先后就是对话真实发生的
 *    先后；流式重投影不得改变已出现的相对顺序。
 * 2. 委派任务（主代理 → 子代理的第一条）永远是第一条：它是这次委派的开场用户回合，
 *    即使承载它的调用行在来源里排在邮件行之后。
 * 3. 每条"发消息"行贡献一个用户回合（主代理发给子代理的内容），紧接着是**同一行**
 *    触发的子代理过程与结论（紧邻、且指令在前）。重投影时整块原地替换，不追加到结尾。
 * 4. 每条"收到消息"行贡献一个助手回合（子代理 → 主代理的答复），位置就是它在来源里的位置。
 */
const WORKER = 'worker'
const SESSION = 'sub-1'

function message(parts: MessagePart[]): CoreMessage[] {
  return [{ id: 'm-1', role: 'assistant', content: '', timestamp: '2026-10-12T00:00:00.000Z', parts }]
}

function meta(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { agent_name: WORKER, sub_session_id: SESSION, ...extra }
}

function callRow(): MessagePart {
  return {
    id: 'row-call',
    partType: 'agent_summary',
    status: 'running',
    content: '',
    toolName: 'sub_agent',
    toolArgs: { task: '第一次任务' },
    metadata: meta(),
  }
}

function sentRow(id: string, prompt: string, child: MessagePart[]): MessagePart {
  return {
    id,
    partType: 'tool_call',
    status: 'running',
    content: 'accepted',
    label: 'sub_agent_message',
    toolName: 'sub_agent_message',
    toolArgs: { prompt },
    metadata: meta({ subLineParts: child }),
  }
}

function receivedRow(id: string, answer: string): MessagePart {
  return {
    id,
    partType: 'tool_call',
    status: 'completed',
    content: answer,
    label: 'sub_agent_receive',
    toolName: 'sub_agent_receive',
    metadata: meta(),
  }
}

function child(id: string, content: string): MessagePart {
  return { id, partType: 'model_text', status: 'completed', content }
}

function timelineOf(parts: MessagePart[]): Array<{ role: string; content: string }> {
  const run = selectCoreSubAgentRun(message(parts), { subSessionId: SESSION, name: WORKER })
  return (run?.timeline ?? []).map(item => ({ role: item.role, content: item.content }))
}

describe('sub-agent timeline order', () => {
  it('keeps the delegation chronology: task, then each instruction before the work it triggered', () => {
    expect(timelineOf([
      callRow(),
      sentRow('row-sent-a', '再补第一段', [child('a-1', '第一段工作')]),
      receivedRow('row-received-a', '第一段结论'),
      sentRow('row-sent-b', '再补第二段', [child('b-1', '第二段工作')]),
      receivedRow('row-received-b', '第二段结论'),
    ])).toEqual([
      { role: 'user', content: '第一次任务' },
      { role: 'user', content: '再补第一段' },
      { role: 'assistant', content: '第一段工作' },
      { role: 'assistant', content: '第一段结论' },
      { role: 'user', content: '再补第二段' },
      { role: 'assistant', content: '第二段工作' },
      { role: 'assistant', content: '第二段结论' },
    ])
  })

  it('puts the task first even when the call row arrives after a mailbox row', () => {
    // 后端把子代理的邮件行与调用行分开投递时，调用行可能排在后面；任务仍是开场。
    const ordered = timelineOf([
      sentRow('row-sent-a', '先照着上一轮继续', [child('a-1', '继续的工作')]),
      callRow(),
    ])
    expect(ordered[0]).toEqual({ role: 'user', content: '第一次任务' })
    expect(ordered.slice(1)).toEqual([
      { role: 'user', content: '先照着上一轮继续' },
      { role: 'assistant', content: '继续的工作' },
    ])
  })

  it('does not append an instruction after its own streamed block while the row streams', () => {
    // 同一行随流式重投影：整块原地替换（顺序不变），不会把新的内容追加到时间线末尾。
    const rowWith = (content: string): MessagePart => sentRow('row-sent-a', '边做边补', [child('a-1', content)])
    const first = timelineOf([callRow(), rowWith('第一块')])
    const second = timelineOf([callRow(), rowWith('第一块'), rowWith('第一块第二块')])
    expect(first[1]).toEqual({ role: 'user', content: '边做边补' })
    expect(second[1]).toEqual({ role: 'user', content: '边做边补' })
    expect(second[2]).toEqual({ role: 'assistant', content: '第一块第二块' })
    expect(second).toHaveLength(3)
  })

  it('shows the same order in the full session projection', () => {
    const parts = [
      callRow(),
      sentRow('row-sent-a', '再补第一段', [child('a-1', '第一段工作')]),
      receivedRow('row-received-a', '第一段结论'),
    ]
    const full = selectCoreSubAgentRuns(message(parts))[0]
    expect(full.timeline.map(item => item.content)).toEqual(['第一次任务', '再补第一段', '第一段工作', '第一段结论'])
  })
})
