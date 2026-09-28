/**
 * The plan package (方案) as both hosts store it.
 *
 * `core/protocol/plan-package-v1-fixtures.json` is the contract of record and
 * both hosts run it through their own implementation. These types mirror it for
 * the shared UI: the phone and the desktop render the same package, so a field
 * name here must match the fixtures, not one host's convenience.
 */

export const PLAN_STATUSES = ['draft', 'ready', 'executing', 'done', 'archived'] as const
export type PlanStatus = (typeof PLAN_STATUSES)[number]

export const PLAN_STEP_STATUSES = [
  'pending',
  'in_progress',
  'completed',
  'blocked',
  'skipped',
  'replaced',
] as const
export type PlanStepStatus = (typeof PLAN_STEP_STATUSES)[number]

export const PLAN_DOC_KINDS = ['research', 'spec', 'design', 'plan', 'tasks', 'notes'] as const
export type PlanDocKind = (typeof PLAN_DOC_KINDS)[number]

export type PlanQuestionStatus = 'open' | 'answered'
export type PlanRiskSeverity = 'low' | 'medium' | 'high'

export interface PlanRequirement {
  restatement: string
  success_looks_like: string
  non_goals: string[]
  assumptions: string[]
}

export interface PlanQuestion {
  id: string
  question: string
  status: PlanQuestionStatus
  answer: string
}

export interface RejectedApproach {
  option: string
  why: string
}

export interface PlanApproach {
  chosen: string
  why: string
  rejected: RejectedApproach[]
}

/** Field-for-field the session checklist's step shape, so execution installs it as-is. */
export interface PlanStep {
  id: string
  description: string
  deliverables: string[]
  status: PlanStepStatus
}

export interface PlanChecklist {
  design_summary: string
  steps: PlanStep[]
  files: string[]
}

/** Field-for-field the durable goal's shape; execution is what creates it. */
export interface PlanGoal {
  objective: string
  completion_criteria: string[]
}

export interface PlanRisk {
  risk: string
  severity: PlanRiskSeverity
  mitigation: string
}

export interface PlanDoc {
  path: string
  kind: PlanDocKind
  title: string
}

export interface PlanExecution {
  thread_id: string
  revision: number
  started_at: string
}

export interface PlanPackage {
  schema_version: number
  plan_id: string
  title: string
  status: PlanStatus
  summary: string
  requirement: PlanRequirement
  open_questions: PlanQuestion[]
  approach: PlanApproach
  checklist: PlanChecklist
  goal: PlanGoal
  risks: PlanRisk[]
  docs: PlanDoc[]
  execution: PlanExecution | null
  /** Host-local below here: the project it belongs to, who wrote this revision, and when. */
  project_id: string
  source: string
  revision: number
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface PlanRevisionSummary {
  revision: number
  title: string
  status: PlanStatus
  source: string
  created_at: string
}

/** A save payload: the fields present are applied, the rest keep stored values. */
export type PlanPatch = Partial<Omit<PlanPackage, 'revision' | 'source'>> & {
  plan_id?: string
  expected_revision?: number
}

export function isPlanPackage(value: unknown): value is PlanPackage {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<PlanPackage>
  return (
    typeof candidate.plan_id === 'string' &&
    typeof candidate.title === 'string' &&
    typeof candidate.status === 'string' &&
    Array.isArray(candidate.checklist?.steps)
  )
}

/** How many steps are finished, for a list row. */
export function planStepProgress(plan: PlanPackage): { done: number; total: number } {
  const steps = plan.checklist?.steps || []
  const done = steps.filter((step) => step.status === 'completed' || step.status === 'skipped').length
  return { done, total: steps.length }
}

/** Open questions block a plan from being ready, and the list says so. */
export function planOpenQuestionCount(plan: PlanPackage): number {
  return (plan.open_questions || []).filter((question) => question.status === 'open').length
}
