import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { hydrateSnapshot, selectCoreWorkbenchMessages } from '../src/appServer'
import { selectPendingCoreDecisions } from '../src/appServer/pendingDecisions'
import CoreSubAgentPane from '../src/components/CoreSubAgentPane.vue'
import CorePendingDecisionPanel from '../src/components/CorePendingDecisionPanel.vue'
import type { CoreAppSnapshot } from '../src/appServer'
import type { CoreMessage, CoreSubAgentRun } from '../src/types'
import { createFakeTransport } from './fake-transport'

const testTransport = createFakeTransport()

/** A sub-agent tool row carrying the child's own waiting request as a nested
 *  line item — the shape the runtime projection must produce for the main
 *  interface to see a sub-agent's question/approval at all. */
function nestedRequestSnapshot(toolName: string, requestId: string): CoreAppSnapshot {
  return hydrateSnapshot({
    thread_id: 'thread-ask',
    snapshot_seq: 6,
    status: 'running',
    turns: { 'turn-1': { turn_id: 'turn-1', status: 'running', items: ['parent-1', 'ask-1'] } },
    core: {
      thread_id: 'thread-ask',
      snapshot_seq: 6,
      status: 'running',
      turns: { 'turn-1': { turn_id: 'turn-1', status: 'running', items: ['parent-1', 'ask-1'] } },
      item_order: ['parent-1', 'ask-1'],
      items: {
        'parent-1': {
          item_id: 'parent-1',
          turn_id: 'turn-1',
          kind: 'tool_call',
          status: 'running',
          payload: {
            type: 'dynamicToolCall',
            tool_name: 'sub_agent',
            arguments: { action: 'run', prompt: '后台任务' },
            metadata: { sub_session_id: 'sub-1', agent_name: 'worker' },
          },
        },
        'ask-1': {
          item_id: 'ask-1',
          turn_id: 'turn-1',
          parent_item_id: 'parent-1',
          kind: 'approval_request',
          status: 'pending',
          request_id: requestId,
          payload: {
            type: 'serverRequest',
            tool_name: toolName,
            request_id: requestId,
            question: '要交付哪个格式？',
            options: [{ id: 'md', label: 'Markdown' }, { id: 'pdf', label: 'PDF' }],
          },
        },
      },
      requests: {
        [requestId]: { request_id: requestId, status: 'pending', item_id: 'ask-1', turn_id: 'turn-1' },
      },
      artifacts: {},
    },
  })
}

function projected(toolName: string, requestId: string): CoreMessage[] {
  return selectCoreWorkbenchMessages(nestedRequestSnapshot(toolName, requestId)) as unknown as CoreMessage[]
}

function paneRun(parts: CoreSubAgentRun['timeline'][number]['parts']): CoreSubAgentRun {
  return {
    id: 'thread-1:sub:worker',
    subSessionId: 'thread-1:sub:worker',
    name: 'worker',
    task: '后台任务',
    status: 'running',
    modelId: 'deepseek/deepseek-v4.1-flash',
    startedAt: '2026-10-12T00:00:00.000Z',
    updatedAt: '2026-10-12T00:01:00.000Z',
    timeline: [{ id: 'sub-answer', role: 'assistant', content: '', timestamp: '', parts }],
    sourcePartIds: [],
  }
}

describe('sub-agent interactive requests', () => {
  it('surfaces a nested sub-agent question in the main interface, with its owner and request id', () => {
    const pending = selectPendingCoreDecisions(projected('question', 'req-q'))

    expect(pending).toHaveLength(1)
    const [decision] = pending
    expect(decision.requestId).toBe('req-q')
    expect(decision.isQuestion).toBe(true)
    expect(decision.canGuide).toBe(true)
    // 归属：回答要回到发问的那个子代理，而不是主代理。
    expect(decision.subAgentName).toBe('worker')
    expect(decision.subAgentSessionId).toBe('sub-1')
    expect(decision.options.map(option => option.id)).toEqual(['md', 'pdf'])
  })

  it('surfaces a nested sub-agent approval too, and labels it as an approval', () => {
    const pending = selectPendingCoreDecisions(projected('run_shell', 'req-a'))

    expect(pending).toHaveLength(1)
    expect(pending[0].requestId).toBe('req-a')
    expect(pending[0].isQuestion).toBe(false)
    expect(pending[0].kindLabel).toBe('审批')
    expect(pending[0].subAgentName).toBe('worker')
  })

  it('names the asking sub-agent in the composer takeover panel', async () => {
    const wrapper = mount(CorePendingDecisionPanel, {
      props: { items: selectPendingCoreDecisions(projected('question', 'req-q')) },
    })
    await nextTick()
    const origin = wrapper.find('[data-pending-decision-origin]')
    expect(origin.exists()).toBe(true)
    expect(origin.text()).toContain('worker')
    expect(origin.text()).toContain('提问')
    wrapper.unmount()
  })

  it('forwards a decision answered inside the sub-agent panel to the host', async () => {
    const decision = {
      id: 'ask-1',
      partType: 'decision' as const,
      status: 'pending' as const,
      content: '',
      toolName: 'question',
      label: '要交付哪个格式？',
      metadata: {
        waitingRequest: {
          kind: 'question',
          request_id: 'req-q',
          options: [{ id: 'md', label: 'Markdown' }],
        },
      },
    }
    const wrapper = mount(CoreSubAgentPane, {
      props: { run: paneRun([decision]), transport: testTransport, teleportTo: 'body' },
    })
    await nextTick()

    const pane = document.body.querySelector<HTMLElement>('[data-sub-agent-pane]')
    const option = pane?.querySelector<HTMLButtonElement>('.decision-option')
    expect(option).toBeTruthy()
    option!.click()
    await nextTick()

    const emitted = wrapper.emitted('decision-select')
    expect(emitted).toHaveLength(1)
    expect(emitted?.[0]?.[0]).toMatchObject({ partId: 'ask-1' })
    wrapper.unmount()
    document.body.querySelectorAll('[data-sub-agent-pane]').forEach(element => element.remove())
  })
})
