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

  it('keeps the latest checklist from the current turn after the final answer arrives', () => {
    const groups = buildCurrentTurnChecklistGroups([
      { id: 'user:new', role: 'user', content: 'new task', timestamp: '', parts: [] },
      { id: 'assistant:tool', role: 'assistant', content: '', timestamp: '', parts: [checklistPart] },
      { id: 'assistant:final', role: 'assistant', content: 'done', timestamp: '', parts: [] },
    ])

    expect(groups[0]?.id).toBe('assistant:tool:checklist')
    expect(groups[0]?.steps).toHaveLength(2)
  })
})
