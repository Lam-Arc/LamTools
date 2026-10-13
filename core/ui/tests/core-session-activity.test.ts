import { describe, expect, it } from 'vitest'
import { hydrateSnapshot, selectCoreSessionActivity, selectCoreWorkbenchMessages } from '../src/appServer'
import type { CoreAppSnapshot } from '../src/appServer'
import type { CoreMessage, MessagePartStatus } from '../src/types'

function snapshotWithStatus(status: string): CoreAppSnapshot {
  return hydrateSnapshot({
    thread_id: 'thread-activity',
    snapshot_seq: 3,
    status: status as CoreAppSnapshot['status'],
    core: {
      thread_id: 'thread-activity',
      snapshot_seq: 3,
      status: status as CoreAppSnapshot['status'],
      turns: {},
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
    },
  })
}

function assistantMessage(id: string, parts: CoreMessage['parts']): CoreMessage {
  return { id, role: 'assistant', content: '', timestamp: '2026-07-18T00:00:00.000Z', parts }
}

function agentPart(status: MessagePartStatus): NonNullable<CoreMessage['parts']>[number] {
  return {
    id: 'agent-' + status,
    partType: 'agent_summary',
    status,
    content: status === 'completed' ? '已完成。' : '',
    toolName: 'sub_agent',
    toolArgs: { task: '后台任务' },
    metadata: {
      sub_session_id: 'sub-' + status,
      agent_name: 'worker',
      subLineParts: [],
    },
  }
}

describe('selectCoreSessionActivity', () => {
  it('is idle for a null snapshot', () => {
    const activity = selectCoreSessionActivity(null)
    expect(activity.status).toBe('idle')
    expect(activity.mainRunning).toBe(false)
    expect(activity.awaitingSubAgents).toBe(false)
    expect(activity.pendingSubAgentCount).toBe(0)
    expect(activity.memberStatuses).toEqual({})
    expect(activity.phase).toBe('idle')
  })

  it('reads each member own status from its per-member row, mid-turn', () => {
    // 后端在成员每次生命周期变化时发布一行（payload.type=subAgentStatus）：回合还没
    // 结束也能把状态标签修准，不必等回合终结或监督者记录的下一次轮询。
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-activity',
      snapshot_seq: 6,
      status: 'running',
      core: {
        thread_id: 'thread-activity',
        snapshot_seq: 6,
        status: 'running',
        turns: {
          'turn-1': { turn_id: 'turn-1', status: 'running', items: ['run-1:status', 'run-2:status'] },
        },
        items: {
          'run-1:status': {
            item_id: 'run-1:status',
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: { type: 'subAgentStatus', tool_name: 'sub_agent', sub_agent: { name: 'writer', status: 'idle' } },
          },
          'run-2:status': {
            item_id: 'run-2:status',
            turn_id: 'turn-1',
            kind: 'message',
            status: 'running',
            payload: { type: 'subAgentStatus', tool_name: 'sub_agent', sub_agent: { name: 'renderer', status: 'running' } },
          },
          'stale:status': {
            item_id: 'stale:status',
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: { type: 'subAgentStatus', tool_name: 'sub_agent', sub_agent: { name: 'stale', status: 'idle' } },
          },
        },
        item_order: ['run-1:status', 'run-2:status'],
        requests: {},
        artifacts: {},
      },
    } as CoreAppSnapshot)

    const activity = selectCoreSessionActivity(snapshot)
    // 名字小写做键；状态是归一化后的成员状态（idle 就是空闲，不是"已完成"）。
    expect(activity.memberStatuses).toEqual({ writer: 'idle', renderer: 'running' })
    // 不在本轮条目里的行不参与（成员状态属于当前回合）。
    expect(activity.memberStatuses.stale).toBeUndefined()
  })

  it('reports state (a) while the main turn is running', () => {
    const activity = selectCoreSessionActivity(snapshotWithStatus('running'), {
      // A foreground sub-agent can be streaming while the main turn waits on it;
      // the main agent working wins, so this never reads as state (b).
      messages: [assistantMessage('parent', [agentPart('running')])],
    })
    expect(activity.mainRunning).toBe(true)
    expect(activity.awaitingSubAgents).toBe(false)
    expect(activity.pendingSubAgentCount).toBe(0)
    expect(activity.phase).toBe('running')
  })

  it('reports state (b) when the main turn is over but a sub-agent still runs', () => {
    const activity = selectCoreSessionActivity(snapshotWithStatus('completed'), {
      messages: [assistantMessage('parent', [agentPart('running')])],
    })
    expect(activity.mainRunning).toBe(false)
    expect(activity.awaitingSubAgents).toBe(true)
    expect(activity.pendingSubAgentCount).toBe(1)
    expect(activity.phase).toBe('awaiting_sub_agents')
  })

  it('treats a pending sub-agent as outstanding too', () => {
    const activity = selectCoreSessionActivity(snapshotWithStatus('idle'), {
      messages: [assistantMessage('parent', [agentPart('pending')])],
    })
    expect(activity.awaitingSubAgents).toBe(true)
    expect(activity.pendingSubAgentCount).toBe(1)
    expect(activity.phase).toBe('awaiting_sub_agents')
  })

  it('falls back to idle once every sub-agent has settled', () => {
    const activity = selectCoreSessionActivity(snapshotWithStatus('completed'), {
      messages: [assistantMessage('parent', [agentPart('completed')])],
    })
    expect(activity.mainRunning).toBe(false)
    expect(activity.awaitingSubAgents).toBe(false)
    expect(activity.pendingSubAgentCount).toBe(0)
    expect(activity.phase).toBe('idle')
  })

  it('reads the authoritative turn signal and its member names', () => {
    // 主代理把回合挂在后台成员上：turn 上的 waiting_on_members 是真源，不再靠推断。
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-members',
      snapshot_seq: 4,
      status: 'running',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: [],
          waiting_on_members: true,
          running_members: ['renderer_dev', 'sim_tester'],
        },
      },
      core: {
        thread_id: 'thread-members',
        snapshot_seq: 4,
        status: 'running',
        turns: {
          'turn-1': {
            turn_id: 'turn-1',
            status: 'running',
            items: [],
            waiting_on_members: true,
            running_members: ['renderer_dev', 'sim_tester'],
          },
        },
        items: {},
        item_order: [],
        requests: {},
        artifacts: {},
      },
    })

    const activity = selectCoreSessionActivity(snapshot, {
      // The transcript carries no running sub-agent part; the signal alone decides.
      messages: [],
    })
    expect(activity.mainRunning).toBe(false)
    expect(activity.awaitingSubAgents).toBe(true)
    expect(activity.pendingSubAgentCount).toBe(2)
    expect(activity.pendingSubAgentNames).toEqual(['renderer_dev', 'sim_tester'])
    expect(activity.phase).toBe('awaiting_sub_agents')
  })

  it('uses only the latest turn signal while preserving a completed turn that still waits on members', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-latest-member-signal',
      snapshot_seq: 9,
      status: 'completed',
      turns: {
        'turn-old': {
          turn_id: 'turn-old', status: 'completed', seq: 1, items: [],
          waiting_on_members: true, running_members: ['old_worker'],
        },
        'turn-latest': {
          turn_id: 'turn-latest', status: 'completed', seq: 2, items: [],
          waiting_on_members: true, running_members: ['current_worker'],
        },
      },
      core: {
        thread_id: 'thread-latest-member-signal',
        snapshot_seq: 9,
        status: 'completed',
        turns: {
          'turn-old': { turn_id: 'turn-old', status: 'completed', items: [] },
          'turn-latest': { turn_id: 'turn-latest', status: 'completed', items: [] },
        },
        items: {},
        item_order: [],
        requests: {},
        artifacts: {},
      },
    })

    const stillWaiting = selectCoreSessionActivity(snapshot, { messages: [] })
    expect(stillWaiting.awaitingSubAgents).toBe(true)
    expect(stillWaiting.pendingSubAgentNames).toEqual(['current_worker'])

    const newerTurn = hydrateSnapshot({
      ...snapshot,
      snapshot_seq: 10,
      turns: {
        ...snapshot.turns,
        'turn-newer': {
          turn_id: 'turn-newer', status: 'completed', seq: 3, items: [],
          waiting_on_members: false, running_members: [],
        },
      },
      core: {
        ...snapshot.core!,
        snapshot_seq: 10,
        turns: {
          ...snapshot.core!.turns,
          'turn-newer': { turn_id: 'turn-newer', status: 'completed', items: [] },
        },
      },
    })
    const settled = selectCoreSessionActivity(newerTurn, { messages: [] })
    expect(settled.awaitingSubAgents).toBe(false)
    expect(settled.pendingSubAgentCount).toBe(0)
    expect(settled.phase).toBe('idle')
  })

  it('reads the live subAgents item when the turn has no flag yet', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-item',
      snapshot_seq: 5,
      status: 'completed',
      core: {
        thread_id: 'thread-item',
        snapshot_seq: 5,
        status: 'completed',
        turns: {},
        item_order: ['turn-9:sub-agent-wait'],
        items: {
          'turn-9:sub-agent-wait': {
            item_id: 'turn-9:sub-agent-wait',
            turn_id: 'turn-9',
            kind: 'status',
            status: 'running',
            payload: {
              type: 'subAgents',
              status: 'running',
              waiting_on_members: true,
              members: [{ name: 'worker' }],
            },
          },
        },
        requests: {},
        artifacts: {},
      },
    })

    const activity = selectCoreSessionActivity(snapshot, { messages: [] })
    const sameSnapshot = selectCoreSessionActivity(snapshot, { messages: [] })
    expect(activity.awaitingSubAgents).toBe(true)
    expect(activity.pendingSubAgentNames).toEqual(['worker'])
    expect(sameSnapshot.pendingSubAgentNames).toBe(activity.pendingSubAgentNames)
    expect(activity.phase).toBe('awaiting_sub_agents')

    const core = snapshot.core!
    const itemId = 'turn-9:sub-agent-wait'
    const item = core.items![itemId]
    const nextSnapshot: CoreAppSnapshot = {
      ...snapshot,
      snapshot_seq: snapshot.snapshot_seq + 1,
      core: {
        ...core,
        snapshot_seq: (core.snapshot_seq || 0) + 1,
        items: {
          ...core.items,
          [itemId]: {
            ...item,
            payload: { ...item.payload, members: [{ name: 'worker-next' }] },
          },
        },
      },
    }
    const nextActivity = selectCoreSessionActivity(nextSnapshot, { messages: [] })
    expect(nextActivity.pendingSubAgentNames).toEqual(['worker-next'])
    expect(nextActivity.pendingSubAgentNames).not.toBe(activity.pendingSubAgentNames)
  })

  it('lets the drained report clear state (b) even while a transcript part still looks running', () => {
    // 报告事件把 waiting_on_members 置 false：真源说主代理不在等成员，就不显示状态 b，
    // 哪怕过程里那条委派行还残留 running（推断只作兜底）。
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-drained',
      snapshot_seq: 6,
      status: 'completed',
      turns: { 'turn-1': { turn_id: 'turn-1', status: 'completed', items: [], waiting_on_members: false, running_members: [] } },
      core: {
        thread_id: 'thread-drained',
        snapshot_seq: 6,
        status: 'completed',
        turns: { 'turn-1': { turn_id: 'turn-1', status: 'completed', items: [], waiting_on_members: false, running_members: [] } },
        items: {},
        item_order: [],
        requests: {},
        artifacts: {},
      },
    })

    const activity = selectCoreSessionActivity(snapshot, {
      messages: [assistantMessage('parent', [agentPart('running')])],
    })
    expect(activity.awaitingSubAgents).toBe(false)
    expect(activity.phase).toBe('idle')
  })

  it('keeps the member-wait machine row out of the transcript', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-row',
      snapshot_seq: 8,
      status: 'running',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: ['answer-1', 'turn-1:sub-agent-wait'],
          waiting_on_members: true,
          running_members: ['worker'],
        },
      },
      core: {
        thread_id: 'thread-row',
        snapshot_seq: 8,
        status: 'running',
        turns: { 'turn-1': { turn_id: 'turn-1', status: 'running', items: ['answer-1', 'turn-1:sub-agent-wait'] } },
        item_order: ['answer-1', 'turn-1:sub-agent-wait'],
        items: {
          'answer-1': {
            item_id: 'answer-1',
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: { type: 'agentMessage', content: '正文' },
          },
          'turn-1:sub-agent-wait': {
            item_id: 'turn-1:sub-agent-wait',
            turn_id: 'turn-1',
            kind: 'status',
            status: 'running',
            payload: { type: 'subAgents', status: 'running', waiting_on_members: true, members: [{ name: 'worker' }] },
          },
        },
        requests: {},
        artifacts: {},
      },
    })

    const messages = selectCoreWorkbenchMessages(snapshot)
    const partIds = messages.flatMap(message => (message.parts ?? []).map(part => part.id))
    expect(partIds).not.toContain('turn-1:sub-agent-wait')
    expect(partIds).toContain('answer-1')
    // The signal is still readable from the same snapshot.
    expect(selectCoreSessionActivity(snapshot).awaitingSubAgents).toBe(true)
  })

  it('exposes the published members fact for member-level settling', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-members-fact',
      snapshot_seq: 4,
      status: 'running',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: [],
          waiting_on_members: true,
          running_members: ['worker_a', 'worker_b'],
        },
      },
      core: {
        thread_id: 'thread-members-fact',
        snapshot_seq: 4,
        status: 'running',
        turns: {
          'turn-1': {
            turn_id: 'turn-1',
            status: 'running',
            items: [],
            waiting_on_members: true,
            running_members: ['worker_a', 'worker_b'],
          },
        },
        items: {},
        item_order: [],
        requests: {},
        artifacts: {},
      },
    })

    const activity = selectCoreSessionActivity(snapshot, { messages: [] })
    expect(activity.memberWaitKnown).toBe(true)
    expect(activity.memberWaitWaiting).toBe(true)
    expect(activity.runningMemberNames).toEqual(['worker_a', 'worker_b'])
  })

  it('publishes an empty running list when the drain report cleared it', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-members-drained',
      snapshot_seq: 5,
      status: 'completed',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'completed', items: [], waiting_on_members: false, running_members: [] },
      },
      core: {
        thread_id: 'thread-members-drained',
        snapshot_seq: 5,
        status: 'completed',
        turns: {
          'turn-1': { turn_id: 'turn-1', status: 'completed', items: [], waiting_on_members: false, running_members: [] },
        },
        items: {},
        item_order: [],
        requests: {},
        artifacts: {},
      },
    })

    const activity = selectCoreSessionActivity(snapshot, { messages: [] })
    expect(activity.memberWaitKnown).toBe(true)
    expect(activity.memberWaitWaiting).toBe(false)
    expect(activity.runningMemberNames).toEqual([])
  })

  it('reports no members fact when the snapshot never carried one', () => {
    const activity = selectCoreSessionActivity(snapshotWithStatus('running'), { messages: [] })
    expect(activity.memberWaitKnown).toBe(false)
    expect(activity.runningMemberNames).toEqual([])
  })
})
