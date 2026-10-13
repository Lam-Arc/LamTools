import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { selectCoreSubAgentRun, selectCoreSubAgentRuns } from '../src/agents/subAgentProjection'
import type { CoreMessage, MessagePart } from '../src/types'

function assistantMessage(id: string, parts: CoreMessage['parts']): CoreMessage {
  return { id, role: 'assistant', content: '', timestamp: '2026-07-18T00:00:00.000Z', parts }
}

function agentPart(options: {
  id: string
  sessionId: string
  name: string
  status?: 'running' | 'completed'
  childParts?: unknown[]
}): MessagePart {
  return {
    id: options.id,
    partType: 'agent_summary',
    status: options.status ?? 'completed',
    content: '',
    toolName: 'sub_agent',
    toolArgs: { task: `任务 ${options.name}` },
    metadata: {
      sub_session_id: options.sessionId,
      agent_name: options.name,
      subLineParts: options.childParts ?? [],
    },
  }
}

function child(id: string, content: string): Record<string, unknown> {
  return { id, partType: 'tool_call', status: 'completed', content, toolName: 'read_file' }
}

function cleanMessages(): CoreMessage[] {
  return [assistantMessage('parent', [
    agentPart({ id: 'agent-a', sessionId: 'sub-a', name: 'worker_a', childParts: [child('a-1', 'a1'), child('a-2', 'a2')] }),
    agentPart({ id: 'agent-b', sessionId: 'sub-b', name: 'worker_b', status: 'running', childParts: [child('b-1', 'b1')] }),
    agentPart({ id: 'agent-c', sessionId: 'sub-c', name: 'worker_c', childParts: [child('c-1', 'c1'), child('c-2', 'c2'), child('c-3', 'c3')] }),
  ])]
}

describe('selectCoreSubAgentRun (targeted lookup)', () => {
  it('projects only the wanted run: a poisoned other run is never touched', () => {
    // 非目标运行的子过程一旦被投影就会抛错——用它证明定点解析不会去建别的运行。
    const poisonedChild = Object.defineProperty(
      { id: 'poison-child', partType: 'model_text', status: 'completed' },
      'content',
      { get() { throw new Error('non-target child was projected') } },
    )
    const messages = [assistantMessage('parent', [
      agentPart({ id: 'agent-target', sessionId: 'sub-target', name: 'target', status: 'running', childParts: [child('t-1', 't1')] }),
      agentPart({ id: 'agent-other', sessionId: 'sub-other', name: 'other', childParts: [poisonedChild] }),
    ])]

    // 失败前：整会话扫描必然碰到毒条目。
    expect(() => selectCoreSubAgentRuns(messages)).toThrow('non-target child was projected')

    const run = selectCoreSubAgentRun(messages, { subSessionId: 'sub-target', name: 'target' })
    expect(run?.subSessionId).toBe('sub-target')
    expect(run?.name).toBe('target')
    // 任务行 + 子过程段：目标自己的内容照常投影，非目标的毒条目没有被碰。
    expect(run?.task).toBe('任务 target')
    expect(run?.timeline.length).toBeGreaterThan(0)
  })

  it('returns exactly what the full projection would report for that run', () => {
    const messages = cleanMessages()
    const full = selectCoreSubAgentRuns(messages)
    // elapsedMs of a running run is wall-clock; everything else must match.
    const stable = (run: ReturnType<typeof selectCoreSubAgentRun>) => (
      run ? { ...run, elapsedMs: 0 } : run
    )

    for (const ref of [
      { subSessionId: 'sub-a', name: '' },
      { subSessionId: 'sub-b', name: '' },
      { subSessionId: '', name: 'worker_c' },
    ]) {
      const targeted = selectCoreSubAgentRun(messages, ref)
      const expected = full.find(run => (
        ref.subSessionId ? run.subSessionId === ref.subSessionId : run.name === ref.name
      ))
      expect(stable(targeted)).toEqual(stable(expected))
    }
  })

  it('keeps the parts of the run that carry no durable session id', () => {
    // 运行的身份是"代理名"：同一个名字的委派行、邮件行与子过程行属于同一个运行，
    // 其中只有一部分带 sub_session_id（后端发第一条流式事件前还没有子会话）。
    // 只按 sub_session_id 过滤会把同一运行里不带它的那些行整段丢掉——面板于是空着。
    const messages: CoreMessage[] = [assistantMessage('parent', [
      // 这一行自己什么都不产生：没有子过程、没有结论、也没有任务文本。
      {
        id: 'agent-parent',
        partType: 'agent_summary',
        status: 'completed',
        content: '',
        toolName: 'sub_agent',
        metadata: { agent_name: 'worker_a', sub_session_id: 'sub-a' },
      },
      {
        id: 'child-line-1',
        partType: 'sub_line',
        status: 'running',
        label: 'run_command',
        toolName: 'run_command',
        content: '过程 1',
        metadata: { agent_name: 'worker_a' },
      },
      {
        id: 'child-line-2',
        partType: 'sub_line',
        status: 'running',
        label: 'write_file',
        toolName: 'write_file',
        content: '过程 2',
        metadata: { agent_name: 'worker_a' },
      },
    ])]

    const full = selectCoreSubAgentRuns(messages)
    expect(full).toHaveLength(1)
    expect(full[0].timeline.map(message => message.content)).toEqual(['过程 1', '过程 2'])
    expect(full[0].status).toBe('running')

    const targeted = selectCoreSubAgentRun(messages, { subSessionId: 'sub-a', name: 'worker_a' })
    // 面板打开的这一屏必须和整会话投影里的同一个运行一致。
    expect(targeted).toBeDefined()
    expect(targeted?.timeline.map(message => message.content)).toEqual(['过程 1', '过程 2'])
    expect(targeted?.status).toBe('running')
  })

  it('resolves a run the sidebar passes back as a run object', () => {
    // 右栏列表把运行对象原样交回来（带 subSessionId/name，甚至可能是运行键）。
    const messages = cleanMessages()
    const fromList = selectCoreSubAgentRuns(messages).find(run => run.name === 'worker_c')!
    const targeted = selectCoreSubAgentRun(messages, fromList)
    expect(targeted?.name).toBe('worker_c')
    expect(targeted?.timeline.length).toBeGreaterThan(0)
  })

  it('returns undefined for a missing run and an empty ref', () => {
    const messages = cleanMessages()
    expect(selectCoreSubAgentRun(messages, { subSessionId: 'nope', name: '' })).toBeUndefined()
    expect(selectCoreSubAgentRun(messages, { subSessionId: '', name: 'nobody' })).toBeUndefined()
    expect(selectCoreSubAgentRun(messages, '')).toBeUndefined()
  })

  it('accepts a bare session id string, like the sidebar passes', () => {
    expect(selectCoreSubAgentRun(cleanMessages(), 'sub-b')?.subSessionId).toBe('sub-b')
  })

  it('the open pane resolves runs through the targeted lookup, not a full scan', () => {
    const source = readFileSync(resolve(import.meta.dirname, '../src/app/LamToolsApp.vue'), 'utf8')
    expect(source).toContain('selectCoreSubAgentRun(messages.value, ref)')
    expect(source).not.toContain('findCoreSubAgentRun(selectCoreSubAgentRuns')
  })
})
