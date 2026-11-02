import type {
  CoreMessage,
  CoreRuntimeStep,
  CoreRuntimeStepGroup,
  CoreRuntimeStepStatus,
  MessagePart,
} from '@/types.ts'

type ChecklistRecord = Record<string, unknown>

// user:“重启之后想要继续，往往需要发一条用户指令，这样就会让以前的 checklist
// 消失吗？我认为这是不对的？而且不利于缓存命中”+(checklist 表达的是任务的持续
// 计划，不绑定轮次：全量回扫最新 checklist part；中断续跑的内部用户消息、重启
// 后的新指令都不再把它挤出显示窗口。计划本体在后端 state.metadata 里持久存在，
// 这里的扫描只决定卡片显示哪一份，不产生任何新的历史内容。)
export function buildChecklistGroups(messages: CoreMessage[]): CoreRuntimeStepGroup[] {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const candidate = messages[index]
    if (candidate.role !== 'assistant') continue
    const part = [...(candidate.parts || [])].reverse().find((item) => checklistSteps(item).length > 0)
    if (!part) continue

    const steps = checklistSteps(part)
    const metadata = asRecord(part.metadata)
    const taskPlan = asRecord(metadata.task_plan)
    const currentStepId = typeof taskPlan.current_step_id === 'string'
      ? taskPlan.current_step_id
      : undefined
    return [{
      id: `${candidate.id}:checklist`,
      label: 'Checklist',
      status: groupStatus(steps),
      steps,
      ...(currentStepId ? { metadata: { current_step_id: currentStepId } } : {}),
    }]
  }
  return []
}

// user:“重启之后想要继续，往往需要发一条用户指令，这样就会让以前的 checklist
// 消失”+(持久计划兜底：快照组装带回 runtime 会话行里的权威 task_plan，消息流
// 扫描落空（历史窗口裁剪、重启后新轮次还没有 checklist part）时卡片仍有内容)。
export function buildDurableChecklistGroups(taskPlan: unknown): CoreRuntimeStepGroup[] {
  const plan = asRecord(taskPlan)
  const rawSteps = firstArray(plan.steps)
  if (!rawSteps) return []
  const steps = normalizePlanSteps(rawSteps, 'durable:checklist:step')
  if (!steps.length) return []
  const currentStepId = typeof plan.current_step_id === 'string'
    ? plan.current_step_id
    : undefined
  return [{
    id: 'durable:checklist',
    label: 'Checklist',
    status: groupStatus(steps),
    steps,
    ...(currentStepId ? { metadata: { current_step_id: currentStepId } } : {}),
  }]
}

// 两个数据源取更新者：消息里的 checklist part 是写回后的规范快照（_emit_
// checklist_snapshots 发出后同一内核步才落 checkpoint），存在即比持久行新或相等；
// 只有扫描完全落空才回退到持久计划。
export function resolveChecklistGroups(messages: CoreMessage[], taskPlan: unknown): CoreRuntimeStepGroup[] {
  const scanned = buildChecklistGroups(messages)
  return scanned.length > 0 ? scanned : buildDurableChecklistGroups(taskPlan)
}

function checklistSteps(part: MessagePart): CoreRuntimeStep[] {
  if (!isChecklistPart(part)) return []
  const metadata = asRecord(part.metadata)
  const taskPlan = asRecord(metadata.task_plan)
  const args = asRecord(part.toolArgs)
  const rawSteps = firstArray(taskPlan.steps, metadata.plan_steps, args.steps)
  if (!rawSteps) return []

  return normalizePlanSteps(rawSteps, `${part.id}:step`)
}

function normalizePlanSteps(rawSteps: unknown[], idPrefix: string): CoreRuntimeStep[] {
  return rawSteps.flatMap((value, index) => {
    const item = asRecord(value)
    if (!Object.keys(item).length) return []
    const title = String(item.description || item.title || item.text || '').trim()
    if (!title) return []
    const deliverables = Array.isArray(item.deliverables)
      ? item.deliverables.map((value) => String(value).trim()).filter(Boolean)
      : []
    return [{
      id: String(item.id || `${idPrefix}:${index + 1}`),
      title,
      status: normalizeStatus(item.status),
      ...(deliverables.length > 0 ? { deliverables } : {}),
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
