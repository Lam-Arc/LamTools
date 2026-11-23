import { describe, expect, it } from 'vitest'
import { pickSubAgentPane, subAgentTabMatches } from '../src/agents/subAgentTabs'
import type { CoreSubAgentRun } from '../src/types'

function run(overrides: Partial<CoreSubAgentRun> = {}): CoreSubAgentRun {
  return {
    id: 'thread-1:sub:renderer_dev',
    subSessionId: 'thread-1:sub:renderer_dev',
    name: 'renderer_dev',
    task: '渲染器',
    status: 'running',
    modelId: 'deepseek/deepseek-v4.1-flash',
    startedAt: '2026-11-21T09:00:00Z',
    updatedAt: '2026-11-21T09:00:00Z',
    timeline: [],
    sourcePartIds: [],
    ...overrides,
  }
}

// user:“点击子代理的时候若存在分屏则向分屏添加一个子代理标签页…若不存在分屏，则展开一个分屏并显示”+
// (选屏只认辅助分屏：主区里的 agent 标签不可见，放进去等于没开；优先当前所在的辅助屏)。
describe('pickSubAgentPane', () => {
  it('prefers the pane the request came from, then the active auxiliary pane', () => {
    expect(pickSubAgentPane(['main', 'a', 'b'], 'a', 'b')).toBe('b')
    expect(pickSubAgentPane(['main', 'a', 'b'], 'b')).toBe('b')
    expect(pickSubAgentPane(['main', 'a', 'b'], 'main')).toBe('a')
  })

  it('never chooses main, and reports "no split" when only main exists', () => {
    expect(pickSubAgentPane(['main'], 'main')).toBeNull()
    expect(pickSubAgentPane(['main'], 'main', 'main')).toBeNull()
    expect(pickSubAgentPane(['main', 'a'], 'main', 'main')).toBe('a')
  })
})

describe('subAgentTabMatches', () => {
  const current = run()
  const ref = { subSessionId: current.subSessionId, name: current.name }

  it('matches the durable sub-session id, the run id, resumed ids, or the name', () => {
    expect(subAgentTabMatches({ kind: 'agent', resource: current.subSessionId, title: 'x' }, ref, current, '')).toBe(true)
    expect(subAgentTabMatches({ kind: 'agent', resource: current.id, title: 'x' }, ref, current, '')).toBe(true)
    expect(subAgentTabMatches(
      { kind: 'agent', resource: 'thread-1:sub:old', title: 'x' },
      ref,
      run({ subSessionIds: ['thread-1:sub:old'] }),
      '',
    )).toBe(true)
    expect(subAgentTabMatches({ kind: 'agent', resource: '', title: 'RENDERER_DEV' }, ref, undefined, '')).toBe(true)
  })

  it('does not treat the main agent tab or a different session as the same page', () => {
    expect(subAgentTabMatches({ id: 'agent-main', kind: 'agent', title: current.name }, ref, current, '')).toBe(false)
    expect(subAgentTabMatches({ kind: 'agent', sessionId: 'other-thread', title: current.name }, ref, current, 'thread-1')).toBe(false)
    expect(subAgentTabMatches({ kind: 'browser', title: current.name }, ref, current, '')).toBe(false)
  })
})
