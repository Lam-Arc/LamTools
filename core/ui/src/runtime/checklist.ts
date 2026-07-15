import type {
  CoreMessage,
  CoreRuntimeStep,
  CoreRuntimeStepGroup,
  CoreRuntimeStepStatus,
  MessagePart,
} from '../types'

type ChecklistRecord = Record<string, unknown>

export function buildCurrentTurnChecklistGroups(messages: CoreMessage[]): CoreRuntimeStepGroup[] {
  const latestUserIndex = findLastIndex(messages, (message) => message.role === 'user')
  let message: CoreMessage | undefined
  let checklistPart: MessagePart | undefined
  for (let index = messages.length - 1; index > latestUserIndex; index -= 1) {
    const candidate = messages[index]
    if (candidate.role !== 'assistant') continue
    const part = [...(candidate.parts || [])].reverse().find((item) => checklistSteps(item).length > 0)
    if (!part) continue
    message = candidate
    checklistPart = part
    break
  }
  if (!message || !checklistPart) return []

  const steps = checklistSteps(checklistPart)
  return [{
    id: `${message.id}:checklist`,
    label: 'Checklist',
    status: groupStatus(steps),
    steps,
  }]
}

function checklistSteps(part: MessagePart): CoreRuntimeStep[] {
  if (!isChecklistPart(part)) return []
  const metadata = asRecord(part.metadata)
  const taskPlan = asRecord(metadata.task_plan)
  const args = asRecord(part.toolArgs)
  const rawSteps = firstArray(taskPlan.steps, metadata.plan_steps, args.steps)
  if (!rawSteps) return []

  return rawSteps.flatMap((value, index) => {
    const item = asRecord(value)
    if (!Object.keys(item).length) return []
    const title = String(item.description || item.title || item.text || '').trim()
    if (!title) return []
    return [{
      id: String(item.id || `${part.id}:step:${index + 1}`),
      title,
      status: normalizeStatus(item.status),
    }]
  })
}

function isChecklistPart(part: MessagePart): boolean {
  const name = String(part.toolName || part.label || '').toLowerCase()
  return part.partType === 'plan'
    || part.partType === 'todo_update'
    || name.includes('write_checklist')
    || name.includes('update_checklist')
}

function normalizeStatus(value: unknown): CoreRuntimeStepStatus {
  const status = String(value || '').toLowerCase()
  if (status === 'completed' || status === 'complete' || status === 'done') return 'completed'
  if (status === 'in_progress' || status === 'running' || status === 'active') return 'running'
  if (status === 'failed' || status === 'error' || status === 'blocked') return 'failed'
  if (status === 'skipped' || status === 'cancelled' || status === 'canceled') return 'skipped'
  return 'pending'
}

function groupStatus(steps: CoreRuntimeStep[]): CoreRuntimeStepStatus {
  if (steps.some((step) => step.status === 'failed')) return 'failed'
  if (steps.every((step) => step.status === 'completed' || step.status === 'skipped')) return 'completed'
  if (steps.some((step) => step.status === 'running')) return 'running'
  return 'pending'
}

function asRecord(value: unknown): ChecklistRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as ChecklistRecord : {}
}

function firstArray(...values: unknown[]): unknown[] | null {
  return values.find((value): value is unknown[] => Array.isArray(value)) || null
}

function findLastIndex<T>(items: T[], predicate: (item: T) => boolean): number {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (predicate(items[index])) return index
  }
  return -1
}
