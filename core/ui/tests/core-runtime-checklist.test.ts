import { describe, expect, it } from 'vitest'
import { buildCurrentTurnChecklistGroups } from '../src/runtime/checklist'
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

describe('buildCurrentTurnChecklistGroups', () => {
  it('uses only the latest assistant turn checklist', () => {
    const messages: CoreMessage[] = [
      { id: 'assistant:old', role: 'assistant', content: '', timestamp: '', parts: [checklistPart] },
      { id: 'user:new', role: 'user', content: 'new task', timestamp: '', parts: [] },
      { id: 'assistant:new', role: 'assistant', content: 'answer', timestamp: '', parts: [] },
    ]

    expect(buildCurrentTurnChecklistGroups(messages)).toEqual([])
  })

  it('maps the current assistant turn checklist into runtime steps', () => {
    const groups = buildCurrentTurnChecklistGroups([
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
    const groups = buildCurrentTurnChecklistGroups([{
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
    const groups = buildCurrentTurnChecklistGroups([{
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

  it('keeps the latest checklist from the current turn after the final answer arrives', () => {
    const groups = buildCurrentTurnChecklistGroups([
      { id: 'user:new', role: 'user', content: 'new task', timestamp: '', parts: [] },
      { id: 'assistant:tool', role: 'assistant', content: '', timestamp: '', parts: [checklistPart] },
      { id: 'assistant:final', role: 'assistant', content: 'done', timestamp: '', parts: [] },
    ])

    expect(groups[0]?.id).toBe('assistant:tool:checklist')
    expect(groups[0]?.steps).toHaveLength(2)
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
    const groups = buildCurrentTurnChecklistGroups([
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
    const groups = buildCurrentTurnChecklistGroups([
      { id: 'assistant:plan', role: 'assistant', content: '', timestamp: '', parts: [planPart] },
    ])

    expect(groups[0]?.steps).toEqual([
      { id: 'p1', title: '只写标题', status: 'completed' },
      { id: 'p2', title: '跳过项', status: 'skipped' },
    ])
    expect(groups[0]?.status).toBe('completed')
  })
})
