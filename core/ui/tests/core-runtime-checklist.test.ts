import { describe, expect, it } from 'vitest'
import {
  buildChecklistGroups,
  buildDurableChecklistGroups,
  resolveChecklistGroups,
} from '../src/runtime/checklist'
import type { CoreMessage } from '../src/types'

const checklistPart = {
  id: 'checklist-1',
  partType: 'tool_result' as const,
  status: 'completed' as const,
  content: '',
  toolName: 'write_checklist',
  metadata: {
    task_plan: {
      steps: [
        { id: 's1', description: '检查接线', status: 'completed' },
        { id: 's2', description: '完成验证', status: 'in_progress' },
      ],
    },
  },
}

const replacementPart = {
  ...checklistPart,
  id: 'checklist-2',
  toolName: 'write_checklist',
  metadata: {
    task_plan: {
      goal: '新任务',
      steps: [
        { id: 'n1', description: '新任务第一步', status: 'in_progress' },
      ],
    },
  },
}

describe('buildChecklistGroups', () => {
  // user:“重启之后想要继续，往往需要发一条用户指令，这样就会让以前的 checklist
  // 消失吗？我认为这是不对的”+(checklist 与轮次解耦：全量回扫最新 checklist part，
  // 新用户消息/内部续跑消息不再把已有计划挤出显示窗口)。
  it('keeps the checklist across later user messages', () => {
    const messages: CoreMessage[] = [
      { id: 'assistant:old', role: 'assistant', content: '', timestamp: '', parts: [checklistPart] },
      { id: 'user:new', role: 'user', content: 'new task', timestamp: '', parts: [] },
      { id: 'assistant:new', role: 'assistant', content: 'answer', timestamp: '', parts: [] },
    ]

    const groups = buildChecklistGroups(messages)
    expect(groups).toHaveLength(1)
    expect(groups[0]?.id).toBe('assistant:old:checklist')
    expect(groups[0]?.steps).toHaveLength(2)
  })

  it('survives internal interrupted-continue user messages after restart', () => {
    const messages: CoreMessage[] = [
      { id: 'user:task', role: 'user', content: '任务', timestamp: '', parts: [] },
      { id: 'assistant:tool', role: 'assistant', content: '', timestamp: '', parts: [checklistPart] },
      { id: 'user:resume', role: 'user', content: 'Your agent is in interrupted，Continue', timestamp: '', parts: [] },
      { id: 'assistant:resume', role: 'assistant', content: '', timestamp: '', parts: [] },
    ]

    expect(buildChecklistGroups(messages)).toHaveLength(1)
  })

  it('prefers the newest checklist part when a task rewrites the plan', () => {
    const groups = buildChecklistGroups([
      { id: 'assistant:old', role: 'assistant', content: '', timestamp: '', parts: [checklistPart] },
      { id: 'user:new', role: 'user', content: '换个任务', timestamp: '', parts: [] },
      { id: 'assistant:rewrite', role: 'assistant', content: '', timestamp: '', parts: [replacementPart] },
    ])

    expect(groups).toHaveLength(1)
    expect(groups[0]?.id).toBe('assistant:rewrite:checklist')
    expect(groups[0]?.steps[0]?.title).toBe('新任务第一步')
  })

  it('maps the current assistant turn checklist into runtime steps', () => {
    const groups = buildChecklistGroups([
      { id: 'assistant:new', role: 'assistant', content: '', timestamp: '', parts: [checklistPart] },
    ])

    expect(groups).toMatchObject([{
      id: 'assistant:new:checklist',
      label: 'Checklist',
      status: 'running',
      steps: [
        { id: 's1', title: '检查接线', status: 'completed' },
        { id: 's2', title: '完成验证', status: 'running' },
      ],
    }])
  })

  it('projects plan step deliverables without changing empty-step shape', () => {
    const groups = buildChecklistGroups([{
      id: 'assistant:deliverables',
      role: 'assistant',
      content: '',
      timestamp: '',
      parts: [{
        ...checklistPart,
        metadata: {
          task_plan: {
            steps: [
              { id: 's1', description: '检查接线', status: 'completed', deliverables: ['src/main.ts', '  ]'] },
              { id: 's2', description: '完成验证', status: 'in_progress', deliverables: [] },
              { id: 's3', description: '收尾', status: 'pending', deliverables: [''] },
            ],
          },
        },
      }],
    }])

    expect(groups[0]?.steps).toEqual([
      { id: 's1', title: '检查接线', status: 'completed', deliverables: ['src/main.ts', ']'] },
      { id: 's2', title: '完成验证', status: 'running' },
      { id: 's3', title: '收尾', status: 'pending' },
    ])
  })

  it('projects current_step_id for deterministic card selection', () => {
    const groups = buildChecklistGroups([{
      id: 'assistant:current-id',
      role: 'assistant',
      content: '',
      timestamp: '',
      parts: [{
        ...checklistPart,
        metadata: {
          task_plan: {
            current_step_id: 's2',
            steps: [
              { id: 's1', description: '第一步', status: 'in_progress' },
              { id: 's2', description: '第二步', status: 'in_progress' },
            ],
          },
        },
      }],
    }])

    expect(groups[0]?.metadata).toEqual({ current_step_id: 's2' })
  })

  it('maps todo_update parts into runtime steps', () => {
    // Audit 21 S3: the todo_update branch of isChecklistPart had zero
    // coverage. A live todo_update part carries its steps in part.toolArgs.
    const todoUpdatePart = {
      id: 'todo-1',
      partType: 'todo_update' as const,
      status: 'running' as const,
      content: '',
      toolName: 'update_checklist',
      toolArgs: {
        steps: [
          { id: 't1', description: '第一步', status: 'completed' },
          { id: 't2', description: '第二步', status: 'in_progress' },
          { id: 't3', description: '第三步', status: 'pending' },
        ],
      },
    }
    const groups = buildChecklistGroups([
      { id: 'assistant:todo', role: 'assistant', content: '', timestamp: '', parts: [todoUpdatePart] },
    ])

    expect(groups).toMatchObject([{
      id: 'assistant:todo:checklist',
      status: 'running',
      steps: [
        { id: 't1', title: '第一步', status: 'completed' },
        { id: 't2', title: '第二步', status: 'running' },
        { id: 't3', title: '第三步', status: 'pending' },
      ],
    }])
  })

  it('reads plan_steps metadata as an alternative todo_update source', () => {
    const planPart = {
      id: 'plan-1',
      partType: 'todo_update' as const,
      status: 'completed' as const,
      content: '',
      metadata: {
        plan_steps: [
          { id: 'p1', text: '只写标题', status: 'done' },
          { id: 'p2', text: '跳过项', status: 'skipped' },
        ],
      },
    }
    const groups = buildChecklistGroups([
      { id: 'assistant:plan', role: 'assistant', content: '', timestamp: '', parts: [planPart] },
    ])

    expect(groups[0]?.steps).toEqual([
      { id: 'p1', title: '只写标题', status: 'completed' },
      { id: 'p2', title: '跳过项', status: 'skipped' },
    ])
    expect(groups[0]?.status).toBe('completed')
  })
})

describe('buildDurableChecklistGroups', () => {
  it('maps the durable task_plan into the same group shape', () => {
    const groups = buildDurableChecklistGroups({
      goal: 'Task plan',
      current_step_id: 's2',
      steps: [
        { id: 's1', description: '检查接线', status: 'completed' },
        { id: 's2', description: '完成验证', status: 'in_progress' },
      ],
    })

    expect(groups).toMatchObject([{
      id: 'durable:checklist',
      label: 'Checklist',
      status: 'running',
      metadata: { current_step_id: 's2' },
      steps: [
        { id: 's1', title: '检查接线', status: 'completed' },
        { id: 's2', title: '完成验证', status: 'running' },
      ],
    }])
  })

  it('returns nothing for missing or malformed plans', () => {
    expect(buildDurableChecklistGroups(undefined)).toEqual([])
    expect(buildDurableChecklistGroups({})).toEqual([])
    expect(buildDurableChecklistGroups({ steps: 'nope' })).toEqual([])
    expect(buildDurableChecklistGroups('garbage')).toEqual([])
  })
})

describe('resolveChecklistGroups', () => {
  it('falls back to the durable plan when no message part carries one', () => {
    // 重启后 tailTurns 窗口外的历史、或新轮次还没有 checklist part 时，
    // 用快照带回的持久计划兜底，卡片不再消失。
    const groups = resolveChecklistGroups(
      [
        { id: 'user:new', role: 'user', content: '继续', timestamp: '', parts: [] },
        { id: 'assistant:new', role: 'assistant', content: 'answer', timestamp: '', parts: [] },
      ],
      {
        steps: [{ id: 's1', description: '检查接线', status: 'completed' }],
      },
    )

    expect(groups).toMatchObject([{ id: 'durable:checklist', steps: [{ id: 's1' }] }])
  })

  it('prefers the freshest message part over the durable plan', () => {
    const groups = resolveChecklistGroups(
      [
        { id: 'assistant:tool', role: 'assistant', content: '', timestamp: '', parts: [checklistPart] },
      ],
      {
        steps: [{ id: 'stale', description: '过期快照', status: 'pending' }],
      },
    )

    expect(groups[0]?.id).toBe('assistant:tool:checklist')
    expect(groups[0]?.steps[0]?.id).toBe('s1')
  })
})
