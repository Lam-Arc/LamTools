import { describe, expect, it, vi, afterEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { CoreMessage } from '../src/types'

/** Count how often the right panel asks for the sub-agent runs projection. */
const { selectCoreSubAgentRunsSpy } = vi.hoisted(() => ({ selectCoreSubAgentRunsSpy: vi.fn() }))

vi.mock('../src/agents/subAgentProjection', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/agents/subAgentProjection')>()
  return {
    ...actual,
    selectCoreSubAgentRuns: (messages: readonly CoreMessage[]) => {
      selectCoreSubAgentRunsSpy(messages.length)
      return actual.selectCoreSubAgentRuns(messages)
    },
  }
})

import RightSidebarHost from '../src/components/RightSidebarHost.vue'
import { selectCoreSubAgentRuns } from '../src/agents/subAgentProjection'

afterEach(() => {
  document.body.innerHTML = ''
  selectCoreSubAgentRunsSpy.mockClear()
})

function messagesWithSubAgents(): CoreMessage[] {
  return [{
    id: 'm1',
    role: 'assistant',
    content: '',
    timestamp: '',
    parts: [{
      id: 'agent-1',
      partType: 'agent_summary',
      status: 'completed',
      content: '完成。',
      toolName: 'sub_agent',
      metadata: { agent_name: 'worker', sub_session_id: 'sub-1' },
    }],
  }]
}

describe('RightSidebarHost sub-agent scan', () => {  it('does not scan sub-agent runs while the card is hidden', async () => {
    const wrapper = mount(RightSidebarHost, {
      props: { messages: messagesWithSubAgents(), pluginContributions: [] },
      attachTo: document.body,
    })
    await flushPromises()

    // 竖栏图标列表每帧都要渲染，但卡片没开；隐藏状态不得重跑子代理投影。
    expect(selectCoreSubAgentRunsSpy).not.toHaveBeenCalled()

    // 消息继续变化（流式）也不该把它带起来。
    await wrapper.setProps({ messages: messagesWithSubAgents() })
    await flushPromises()
    expect(selectCoreSubAgentRunsSpy).not.toHaveBeenCalled()

    wrapper.unmount()
  })

  it('scans once the card is actually shown', async () => {
    const wrapper = mount(RightSidebarHost, {
      props: { messages: messagesWithSubAgents(), pluginContributions: [] },
      attachTo: document.body,
    })
    await flushPromises()
    selectCoreSubAgentRunsSpy.mockClear()

    await wrapper.get('[data-right-rail-module="sub-agents"]').trigger('mouseenter')
    await flushPromises()

    expect(selectCoreSubAgentRunsSpy).toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('hidden sub-agent projection volume', () => {
  /** 6 个已完成的成员，每个父条目带 20 条子过程。 */
  function heavyMessages(): CoreMessage[] {
    const parts = []
    for (let member = 0; member < 6; member += 1) {
      parts.push({
        id: `agent-${member}`,
        partType: 'agent_summary' as const,
        status: 'completed' as const,
        content: '',
        toolName: 'sub_agent',
        metadata: {
          agent_name: `worker_${member}`,
          sub_session_id: `sub-${member}`,
          subLineParts: Array.from({ length: 20 }, (_, index) => ({
            id: `sub-${member}-part-${index}`,
            partType: 'tool_call' as const,
            status: 'completed' as const,
            content: `步骤 ${index}`,
            toolName: 'read_file',
          })),
        },
      })
    }
    return [{ id: 'm1', role: 'assistant', content: '', timestamp: '', parts }]
  }

  it('rebuilds every finished member timeline on each call, which the hidden rail no longer pays', () => {
    const messages = heavyMessages()
    const runs = selectCoreSubAgentRuns(messages)
    expect(runs).toHaveLength(6)
    // 每个成员的子过程都要在每次扫描里重新归一化成一个 assistant 段。
    const rebuiltParts = runs.reduce(
      (total, run) => total + run.timeline.reduce((parts, message) => parts + (message.parts?.length ?? 0), 0),
      0,
    )
    // 一次扫描重建 120 条子过程；关闭状态下此前每帧一次，现在 0 次。
    expect(rebuiltParts).toBe(120)
  })

  it('counts the live residue an unsettled finished member leaves behind', () => {
    // 成员已经收工，但父条目与子过程都还写着 running（续跑/唤醒后的残留投影）：
    // 投影只能照实说"运行中"，于是这些段留在实时路径上，数量随会话里完成的成员
    // 数增长。分屏现在按监督者状态收敛它们（见 pane 测试），但投影本身仍是这个口径。
    const messages = [{
      id: 'm1',
      role: 'assistant' as const,
      content: '',
      timestamp: '',
      parts: Array.from({ length: 6 }, (_, member) => ({
        id: `agent-${member}`,
        partType: 'agent_summary' as const,
        status: 'running' as const,
        content: '',
        toolName: 'sub_agent',
        metadata: {
          agent_name: `worker_${member}`,
          sub_session_id: `sub-${member}`,
          subLineParts: [{
            id: `sub-${member}-running`,
            partType: 'tool_call' as const,
            status: 'running' as const,
            content: '还在跑',
            toolName: 'read_file',
          }],
        },
      })),
    }]

    const runs = selectCoreSubAgentRuns(messages)
    const liveSegments = runs
      .flatMap(run => run.timeline)
      .filter(message => message.metadata?.live)

    expect(runs.map(run => run.status)).toEqual(Array(6).fill('running'))
    expect(liveSegments).toHaveLength(6)
  })
})
