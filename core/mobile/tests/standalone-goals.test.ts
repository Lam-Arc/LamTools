import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { goalRpc } from '../src/standalone/StandaloneGoals'

const GOAL = {
  id: 'goal_1',
  thread_id: 'thread-1',
  objective: '完成移动端对齐',
  completion_criteria: ['a'],
  status: 'active',
  status_reason: '',
  metadata: {},
  revision: 1,
  created_at: '2026-09-24T00:00:00Z',
  updated_at: '2026-09-24T00:00:00Z',
  completed_at: null,
}

afterEach(() => { invokeMock.mockReset(); vi.unstubAllGlobals() })

describe('standalone goals', () => {
  it('answers the goal RPCs with the desktop payload shapes and patch semantics', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    invokeMock.mockImplementation(async (command: string, args: Record<string, unknown> = {}) => {
      if (command === 'sunday_goal_create') {
        expect(args).toEqual({
          threadId: 'thread-1',
          objective: '完成移动端对齐',
          completionCriteria: ['a'],
          metadata: {},
          goalId: null,
        })
        return { goal: GOAL }
      }
      if (command === 'sunday_goal_get') return { goal: GOAL }
      if (command === 'sunday_goal_list') return { goals: [GOAL] }
      if (command === 'sunday_goal_update') {
        // Fields the caller did not send must arrive as null so the host keeps
        // the stored value — that is what lets the panel clear one field.
        return { goal: { ...GOAL, status: args.status ?? GOAL.status, revision: 2 } }
      }
      throw new Error(`unexpected ${command}`)
    })

    expect(await goalRpc('goal.create', {
      thread_id: 'thread-1', objective: '完成移动端对齐', completion_criteria: ['a'],
    })).toEqual({ goal: GOAL })

    expect(await goalRpc('goal.get', { goal_id: 'goal_1' })).toEqual({ goal: GOAL })
    expect(await goalRpc('goal.list', { thread_id: 'thread-1' })).toEqual({ goals: [GOAL] })
    expect(await goalRpc('goal.list', {})).toEqual({ goals: [GOAL] })

    await goalRpc('goal.update', { goal_id: 'goal_1', status: 'archived' })
    expect(invokeMock).toHaveBeenCalledWith('sunday_goal_update', {
      goalId: 'goal_1',
      objective: null,
      completionCriteria: null,
      status: 'archived',
      statusReason: null,
      metadata: null,
    })

    // A blank status reason is sent as "", not omitted.
    await goalRpc('goal.update', { goal_id: 'goal_1', status_reason: '' })
    expect(invokeMock).toHaveBeenLastCalledWith('sunday_goal_update', {
      goalId: 'goal_1',
      objective: null,
      completionCriteria: null,
      status: null,
      statusReason: '',
      metadata: null,
    })

    await expect(goalRpc('goal.get', {})).rejects.toThrow('goal_id is required')
    await expect(goalRpc('goal.update', {})).rejects.toThrow('goal_id is required')
    // Other methods fall through untouched.
    expect(await goalRpc('artifact.list', {})).toBeNull()
  })
})
