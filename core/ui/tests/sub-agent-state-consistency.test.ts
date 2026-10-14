import { describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RightSidebarHost from '../src/components/RightSidebarHost.vue'
import CoreSubAgentPane from '../src/components/CoreSubAgentPane.vue'
import { subAgentStatusLabel } from '../src/agents/subAgentDisplay'
import { createFakeTransport } from './fake-transport'
import { hydrateSnapshot, selectCoreWorkbenchMessages } from '../src/appServer'
import { reconcileCoreSubAgentRun, resolveCoreSubAgentStatus, selectCoreSubAgentRuns } from '../src/agents/subAgentProjection'
import type { CoreMessage, CoreSubAgentRun } from '../src/types'

function run(): CoreSubAgentRun {
  return {
    id: 'worker', subSessionId: 'parent:sub:worker', sourceMessageId: 'parent-answer',
    sourcePartId: 'parent-call', name: 'worker', task: 'inspect', model: 'fixture',
    status: 'running', startedAt: '2026-10-13T13:13:08Z', timeline: [],
    modelId: 'fixture', updatedAt: '2026-10-13T13:13:08Z', sourcePartIds: ['parent-call'],
  }
}

describe('sub-agent state consistency', () => {
  it('uses a newer interrupted registry record over a stale published running status', () => {
    expect(resolveCoreSubAgentStatus(run(), 'running', {
      status: 'interrupted', completed_at: Date.parse('2026-10-13T14:38:18Z') / 1000,
    })).toBe('interrupted')
  })

  it('allows a new invocation to run after an older interrupted record', () => {
    const newer = { ...run(), startedAt: '2026-10-13T15:00:00Z' }
    expect(resolveCoreSubAgentStatus(newer, 'running', {
      status: 'interrupted', completed_at: Date.parse('2026-10-13T14:38:18Z') / 1000,
    })).toBe('running')
  })

  it.each(['idle', 'completed', 'interrupted', 'failed', 'closed'])('a current terminal record wins over stale published running (%s)', status => {
    const record = { name: 'worker', status, started_at: Date.parse(run().startedAt) / 1000,
      completed_at: Date.parse('2026-10-13T14:38:18Z') / 1000, elapsed_ms: 5110380 }
    const resolved = reconcileCoreSubAgentRun(run(), 'running', record)
    expect(resolved.status).toBe(status === 'failed' ? 'error' : status)
    expect(resolved.completedAt).toBe('2026-10-13T14:38:18.000Z')
    expect(resolved.elapsedMs).toBe(5110380)
  })

  it('does not reopen a completed child from stale running evidence', () => {
    const finished = { ...run(), status: 'idle' as const, completedAt: '2026-10-13T14:38:18Z' }
    expect(resolveCoreSubAgentStatus(finished, 'running', {
      name: 'worker', status: 'running', started_at: Date.parse(run().startedAt) / 1000,
    })).toBe('idle')
  })

  it('a new child start beats an old terminal poll after Resume', () => {
    const finished = { ...run(), status: 'interrupted' as const, completedAt: '2026-10-13T14:38:18Z' }
    const live = { name: 'worker', status: 'running', started_at: Date.parse('2026-10-13T15:00:00Z') / 1000 }
    const old = { name: 'worker', status: 'interrupted', started_at: Date.parse(run().startedAt) / 1000,
      completed_at: Date.parse('2026-10-13T14:38:18Z') / 1000 }
    expect(resolveCoreSubAgentStatus(finished, live, old)).toBe('running')
    expect(resolveCoreSubAgentStatus(finished, old, live)).toBe('running')
  })

  it('ignores a prior terminal even without a published status', () => {
    const newer = { ...run(), startedAt: '2026-10-13T15:00:00Z' }
    expect(resolveCoreSubAgentStatus(newer, undefined, {
      status: 'interrupted', completed_at: Date.parse('2026-10-13T14:38:18Z') / 1000,
    })).toBe('running')
  })

  it('recognizes a hydrated child terminal event without changing parent state', () => {
    const subAgent = {
      name: 'worker', status: 'interrupted', sub_session_id: 'parent:sub:worker',
      started_at: Date.parse('2026-10-13T13:13:08Z') / 1000,
      completed_at: Date.parse('2026-10-13T14:38:18Z') / 1000,
    }
    const snapshot = hydrateSnapshot({
      thread_id: 'parent', snapshot_seq: 3, status: 'running',
      core: {
      thread_id: 'parent', snapshot_seq: 3, status: 'running',
      turns: { 'parent-turn': { turn_id: 'parent-turn', status: 'running', items: ['child-terminal'] } },
      items: {
        'child-terminal': {
          item_id: 'child-terminal', turn_id: 'parent-turn', kind: 'message', status: 'cancelled',
          payload: { type: 'agentMessage', content: 'child interrupted', sub_agent_terminal: true },
          metadata: { sub_agent: subAgent },
        },
      },
      item_order: ['child-terminal'], requests: {}, artifacts: {},
      },
    })
    const messages = selectCoreWorkbenchMessages(snapshot)
    const projected = selectCoreSubAgentRuns(messages)
    expect(projected).toHaveLength(1)
    expect(projected[0].status).toBe('interrupted')
    expect(projected[0].completedAt).toBeTruthy()
    expect(snapshot.status).toBe('running')
    expect(snapshot.core.turns['parent-turn'].status).toBe('running')
  })

  it('does not infer a child interruption from its parent turn completing', () => {
    expect(resolveCoreSubAgentStatus(run(), 'running', undefined)).toBe('running')
  })
})


describe('card and pane status alignment', () => {
  it('reproduces the stale delegation card and follows interruption, completion, and child Resume on both surfaces', async () => {
    const messages: CoreMessage[] = [{ id: 'm1', role: 'assistant', content: '', timestamp: run().startedAt,
      parts: [{ id: 'parent-call', partType: 'agent_summary', status: 'running', content: '', toolName: 'sub_agent',
        metadata: { agent_name: 'worker', sub_session_id: run().subSessionId, status: 'running', model_id: 'fixture' } }] }]
    const registry = { name: 'worker', status: 'interrupted', sub_session_id: run().subSessionId,
      started_at: Date.parse(run().startedAt) / 1000, completed_at: Date.parse('2026-10-13T14:38:18Z') / 1000,
      elapsed_ms: 5110380 }
    const card = mount(RightSidebarHost, { attachTo: document.body,
      props: { messages, memberStatuses: { worker: 'running' }, subAgentDurableRecords: { worker: registry } } })
    const pane = mount(CoreSubAgentPane, { attachTo: document.body, props: { run: run(), transport: createFakeTransport(),
      teleportTo: 'body', memberStatuses: { worker: 'running' }, durableRecord: registry } })
    async function assertBoth(status: string) {
      await flushPromises()
      expect(document.querySelector('[data-sub-agent-item] [data-status]')?.getAttribute('data-status')).toBe(status)
      expect(document.querySelector('.sub-agent-pane-status')?.textContent?.trim()).toBe(subAgentStatusLabel(status))
    }
    try {
      await card.get('[data-right-rail-module="sub-agents"]').trigger('mouseenter')
      await assertBoth('interrupted')  // screenshot: previously card=running, pane=interrupted
      expect(document.querySelector('[data-sub-agent-group="running"]')).toBeNull()
      // Reconnection/hydration can carry the same stale transcript; neither
      // a new parent turn nor a cleared member-status map revives the child.
      await card.setProps({ messages: [...messages], memberStatuses: {} })
      await pane.setProps({ memberStatuses: {} })
      await assertBoth('interrupted')
      const resumed = { ...registry, status: 'running', started_at: Date.parse('2026-10-13T15:00:00Z') / 1000,
        completed_at: null, elapsed_ms: 0 }
      await card.setProps({ memberStatusRecords: { worker: resumed } })
      await pane.setProps({ memberStatusRecords: { worker: resumed } })
      await assertBoth('running') // new child lifecycle beats an in-flight old registry poll
      const done = { ...resumed, status: 'idle', completed_at: Date.parse('2026-10-13T15:10:00Z') / 1000, elapsed_ms: 600000 }
      await card.setProps({ memberStatusRecords: { worker: done }, subAgentDurableRecords: { worker: resumed } })
      await pane.setProps({ memberStatusRecords: { worker: done }, durableRecord: resumed })
      await assertBoth('idle') // terminal event beats an in-flight running registry poll
    } finally { card.unmount(); pane.unmount(); document.body.innerHTML = '' }
  })
})
