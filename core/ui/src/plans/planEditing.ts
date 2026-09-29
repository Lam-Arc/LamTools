/**
 * Editing logic for the plan package workbench.
 *
 * `core/protocol/plan-package-v1-fixtures.json` is the contract of record: every
 * normalisation, default and refusal wording below mirrors a rule in it, so the
 * shared panel behaves the same against the desktop store and the phone host.
 * This module is deliberately free of Vue and of any RPC: the panel and its
 * tests both call it directly.
 */

import {
  PLAN_DOC_KINDS,
  PLAN_STATUSES,
  PLAN_STEP_STATUSES,
  type PlanApproach,
  type PlanChecklist,
  type PlanDoc,
  type PlanDocKind,
  type PlanGoal,
  type PlanPackage,
  type PlanPatch,
  type PlanQuestion,
  type PlanRequirement,
  type PlanRevisionSummary,
  type PlanRisk,
  type PlanRiskSeverity,
  type PlanStatus,
  type PlanStep,
  type PlanStepStatus,
} from './types'

export const PLAN_STATUS_LABELS: Record<PlanStatus, string> = {
  draft: '草稿',
  ready: '就绪',
  executing: '执行中',
  done: '已完成',
  archived: '已归档',
}

export const PLAN_STEP_STATUS_LABELS: Record<PlanStepStatus, string> = {
  pending: '待办',
  in_progress: '进行中',
  completed: '已完成',
  blocked: '受阻',
  skipped: '跳过',
  replaced: '被替换',
}

export const PLAN_DOC_KIND_LABELS: Record<PlanDocKind, string> = {
  research: '调研',
  spec: '规格',
  design: '设计',
  plan: '方案',
  tasks: '任务',
  notes: '笔记',
}

export const PLAN_RISK_SEVERITY_LABELS: Record<PlanRiskSeverity, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

export const PLAN_QUESTION_STATUS_LABELS: Record<PlanQuestion['status'], string> = {
  open: '未答',
  answered: '已答',
}

/**
 * The contract's `status_transitions`. The editor only ever offers a target
 * listed here, so an illegal jump cannot be sent from the UI.
 */
const STATUS_TRANSITIONS: Record<PlanStatus, PlanStatus[]> = {
  draft: ['ready', 'archived'],
  ready: ['draft', 'executing', 'archived'],
  executing: ['done', 'archived'],
  done: ['archived'],
  archived: [],
}

export function planStatusTargets(status: PlanStatus): PlanStatus[] {
  return STATUS_TRANSITIONS[status] || []
}

export function isPlanStatus(value: unknown): value is PlanStatus {
  return typeof value === 'string' && (PLAN_STATUSES as readonly string[]).includes(value)
}

export function isStepStatus(value: unknown): value is PlanStepStatus {
  return typeof value === 'string' && (PLAN_STEP_STATUSES as readonly string[]).includes(value)
}

export function isDocKind(value: unknown): value is PlanDocKind {
  return typeof value === 'string' && (PLAN_DOC_KINDS as readonly string[]).includes(value)
}

export function asRiskSeverity(value: unknown): PlanRiskSeverity {
  return value === 'low' || value === 'high' ? value : 'medium'
}

// ---------------------------------------------------------------------------
// Normalisation
// ---------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function strArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(str).filter((item) => item !== '') : []
}

function trimmedStrings(value: unknown): string[] {
  return strArray(value).map((item) => item.trim()).filter(Boolean)
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

/** A brand-new, unsaved plan the panel can edit before the first save. */
export function emptyPlan(projectId: string): PlanPackage {
  return {
    schema_version: 1,
    plan_id: '',
    title: '',
    status: 'draft',
    summary: '',
    requirement: { restatement: '', success_looks_like: '', non_goals: [], assumptions: [] },
    open_questions: [],
    approach: { chosen: '', why: '', rejected: [] },
    checklist: { design_summary: '', steps: [], files: [] },
    goal: { objective: '', completion_criteria: [] },
    risks: [],
    docs: [],
    execution: null,
    project_id: projectId || '',
    source: '',
    revision: 0,
    created_at: '',
    updated_at: '',
    deleted_at: null,
  }
}

function normalizeRequirement(value: unknown): PlanRequirement {
  const raw = asRecord(value)
  return {
    restatement: str(raw.restatement),
    success_looks_like: str(raw.success_looks_like ?? raw.successLooksLike),
    non_goals: strArray(raw.non_goals ?? raw.nonGoals),
    assumptions: strArray(raw.assumptions),
  }
}

function normalizeQuestion(value: unknown, index: number): PlanQuestion {
  const raw = asRecord(value)
  return {
    id: str(raw.id) || `q${index + 1}`,
    question: str(raw.question),
    status: raw.status === 'answered' ? 'answered' : 'open',
    answer: str(raw.answer),
  }
}

function normalizeApproach(value: unknown): PlanApproach {
  const raw = asRecord(value)
  const rejected = Array.isArray(raw.rejected)
    ? raw.rejected.map((item) => {
      const entry = asRecord(item)
      return { option: str(entry.option), why: str(entry.why) }
    })
    : []
  return { chosen: str(raw.chosen), why: str(raw.why), rejected }
}

function normalizeStep(value: unknown, index: number): PlanStep {
  const raw = asRecord(value)
  return {
    id: str(raw.id) || `s${index + 1}`,
    description: str(raw.description),
    deliverables: strArray(raw.deliverables),
    status: isStepStatus(raw.status) ? raw.status : 'pending',
  }
}

function normalizeChecklist(value: unknown): PlanChecklist {
  const raw = asRecord(value)
  return {
    design_summary: str(raw.design_summary ?? raw.designSummary),
    steps: Array.isArray(raw.steps) ? raw.steps.map(normalizeStep) : [],
    files: strArray(raw.files),
  }
}

function normalizeGoal(value: unknown): PlanGoal {
  const raw = asRecord(value)
  return {
    objective: str(raw.objective),
    completion_criteria: strArray(raw.completion_criteria ?? raw.completionCriteria),
  }
}

function normalizeRisk(value: unknown): PlanRisk {
  const raw = asRecord(value)
  const severity = str(raw.severity)
  return {
    risk: str(raw.risk),
    severity: severity === 'low' || severity === 'high' ? severity : 'medium',
    mitigation: str(raw.mitigation),
  }
}

function normalizeDoc(value: unknown): PlanDoc {
  const raw = asRecord(value)
  const kind = str(raw.kind)
  return {
    path: str(raw.path),
    kind: isDocKind(kind) ? kind : 'notes',
    title: str(raw.title),
  }
}

/**
 * Turn one stored package into the shape the panel edits. Returns null when the
 * value cannot be a plan at all (no id), so a malformed row is skipped instead
 * of rendering a half-empty form.
 */
export function normalizePlan(value: unknown): PlanPackage | null {
  const raw = asRecord(value)
  const planId = str(raw.plan_id ?? raw.planId ?? raw.id).trim()
  if (!planId) return null
  const status = str(raw.status)
  const execution = asRecord(raw.execution)
  const rawQuestions = raw.open_questions ?? raw.openQuestions
  return {
    schema_version: Number(raw.schema_version ?? raw.schemaVersion ?? 1) || 1,
    plan_id: planId,
    title: str(raw.title),
    status: isPlanStatus(status) ? status : 'draft',
    summary: str(raw.summary),
    requirement: normalizeRequirement(raw.requirement),
    open_questions: Array.isArray(rawQuestions)
      ? rawQuestions.map(normalizeQuestion)
      : [],
    approach: normalizeApproach(raw.approach),
    checklist: normalizeChecklist(raw.checklist),
    goal: normalizeGoal(raw.goal),
    risks: Array.isArray(raw.risks) ? raw.risks.map(normalizeRisk) : [],
    docs: Array.isArray(raw.docs) ? raw.docs.map(normalizeDoc) : [],
    execution: raw.execution && Object.keys(execution).length
      ? {
        thread_id: str(execution.thread_id ?? execution.threadId),
        revision: Number(execution.revision) || 0,
        started_at: str(execution.started_at ?? execution.startedAt),
      }
      : null,
    project_id: str(raw.project_id ?? raw.projectId),
    source: str(raw.source),
    revision: Number(raw.revision) || 0,
    created_at: str(raw.created_at ?? raw.createdAt),
    updated_at: str(raw.updated_at ?? raw.updatedAt),
    deleted_at: raw.deleted_at == null ? null : str(raw.deleted_at),
  }
}

export function extractPlans(result: unknown): PlanPackage[] {
  const raw = asRecord(result)
  const rows = Array.isArray(raw.plans)
    ? raw.plans
    : Array.isArray(asRecord(raw.data).plans)
      ? asRecord(raw.data).plans as unknown[]
      : []
  return rows.flatMap((value) => {
    const plan = normalizePlan(value)
    return plan ? [plan] : []
  })
}

export function extractPlan(result: unknown): PlanPackage | null {
  const raw = asRecord(result)
  const direct = normalizePlan(raw.plan)
  if (direct) return direct
  const nested = normalizePlan(asRecord(raw.data).plan)
  if (nested) return nested
  return normalizePlan(raw)
}

export function extractRevisions(result: unknown): PlanRevisionSummary[] {
  const raw = asRecord(result)
  const rows = Array.isArray(raw.revisions)
    ? raw.revisions
    : Array.isArray(asRecord(raw.data).revisions)
      ? asRecord(raw.data).revisions as unknown[]
      : []
  return rows.flatMap((value) => {
    const entry = asRecord(value)
    const revision = Number(entry.revision)
    if (!Number.isFinite(revision) || revision <= 0) return []
    const status = str(entry.status)
    return [{
      revision,
      title: str(entry.title),
      status: isPlanStatus(status) ? status : 'draft',
      source: str(entry.source),
      created_at: str(entry.created_at ?? entry.createdAt),
    }]
  })
}

// ---------------------------------------------------------------------------
// Draft sanitising + patch building
// ---------------------------------------------------------------------------

function nextStepId(steps: PlanStep[]): string {
  let max = 0
  for (const step of steps) {
    const match = /^s(\d+)$/.exec(step.id)
    if (match) max = Math.max(max, Number(match[1]))
  }
  return `s${Math.max(max + 1, steps.length + 1)}`
}

function nextQuestionId(questions: PlanQuestion[]): string {
  let max = 0
  for (const question of questions) {
    const match = /^q(\d+)$/.exec(question.id)
    if (match) max = Math.max(max, Number(match[1]))
  }
  return `q${Math.max(max + 1, questions.length + 1)}`
}

export function addStep(plan: PlanPackage): PlanStep {
  const step: PlanStep = {
    id: nextStepId(plan.checklist.steps),
    description: '',
    deliverables: [],
    status: 'pending',
  }
  plan.checklist.steps.push(step)
  return step
}

export function addQuestion(plan: PlanPackage): PlanQuestion {
  const question: PlanQuestion = {
    id: nextQuestionId(plan.open_questions),
    question: '',
    status: 'open',
    answer: '',
  }
  plan.open_questions.push(question)
  return question
}

/**
 * Apply the contract's normalisation rules to a draft: trim every string, drop
 * blank list items and rows with nothing left in them. The patch is computed
 * from this cleaned copy, so what the panel sends is exactly what the host will
 * store.
 */
export function sanitizePlan(plan: PlanPackage): PlanPackage {
  const requirement: PlanRequirement = {
    restatement: plan.requirement.restatement.trim(),
    success_looks_like: plan.requirement.success_looks_like.trim(),
    non_goals: trimmedStrings(plan.requirement.non_goals),
    assumptions: trimmedStrings(plan.requirement.assumptions),
  }
  const steps: PlanStep[] = plan.checklist.steps.map((step, index) => ({
    id: step.id.trim() || `s${index + 1}`,
    description: step.description.trim(),
    deliverables: trimmedStrings(step.deliverables),
    status: isStepStatus(step.status) ? step.status : 'pending',
  }))
  const rejected = plan.approach.rejected
    .map((entry) => ({ option: entry.option.trim(), why: entry.why.trim() }))
    .filter((entry) => entry.option)
  const questions: PlanQuestion[] = plan.open_questions
    .map((question, index) => ({
      id: question.id.trim() || `q${index + 1}`,
      question: question.question.trim(),
      status: question.status === 'answered' ? 'answered' as const : 'open' as const,
      answer: question.answer.trim(),
    }))
    .filter((question) => question.question)
    // An "answered" question with an empty answer is really still open; keep the
    // two fields from contradicting each other on the way to the host.
    .map((question) => (question.status === 'answered' && !question.answer
      ? { ...question, status: 'open' as const }
      : question))
  return {
    ...plan,
    title: plan.title.trim(),
    summary: plan.summary.trim(),
    requirement,
    open_questions: questions,
    approach: {
      chosen: plan.approach.chosen.trim(),
      why: plan.approach.why.trim(),
      rejected,
    },
    checklist: {
      design_summary: plan.checklist.design_summary.trim(),
      steps,
      files: trimmedStrings(plan.checklist.files),
    },
    goal: {
      objective: plan.goal.objective.trim(),
      completion_criteria: trimmedStrings(plan.goal.completion_criteria),
    },
    risks: plan.risks
      .map((risk) => ({
        risk: risk.risk.trim(),
        severity: (risk.severity === 'low' || risk.severity === 'high' ? risk.severity : 'medium') as PlanRiskSeverity,
        mitigation: risk.mitigation.trim(),
      }))
      .filter((risk) => risk.risk),
    docs: plan.docs
      .map((doc) => ({
        path: doc.path.trim().replace(/\\/g, '/'),
        kind: isDocKind(doc.kind) ? doc.kind : 'notes' as PlanDocKind,
        title: doc.title.trim(),
      }))
      .filter((doc) => doc.path),
  }
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'null'
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  const record = value as Record<string, unknown>
  const keys = Object.keys(record).sort()
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(',')}}`
}

function same(left: unknown, right: unknown): boolean {
  return stableStringify(left) === stableStringify(right)
}

export function clonePlan(plan: PlanPackage): PlanPackage {
  return clone(plan)
}

/**
 * The save payload. For an existing plan this is a true patch: only the fields
 * that changed are present, and `expected_revision` is always sent so a stale
 * writer is refused rather than silently overwriting someone else's revision.
 * For a new plan every editable field is sent and `expected_revision` is
 * omitted (the contract refuses a token for a plan that does not exist yet).
 */
export function buildPlanPatch(original: PlanPackage | null, draft: PlanPackage): PlanPatch {
  const next = sanitizePlan(draft)
  if (!original || !original.plan_id) {
    const patch: PlanPatch = {
      project_id: next.project_id,
      title: next.title,
      summary: next.summary,
      status: next.status,
      requirement: next.requirement,
      approach: next.approach,
      checklist: next.checklist,
      goal: next.goal,
      risks: next.risks,
      docs: next.docs,
      open_questions: next.open_questions,
    }
    if (next.plan_id) patch.plan_id = next.plan_id
    if (!patch.project_id) delete patch.project_id
    return patch
  }

  const previous = sanitizePlan(original)
  const patch: PlanPatch = {
    plan_id: original.plan_id,
    expected_revision: original.revision,
  }
  const projectId = next.project_id || original.project_id
  if (projectId) patch.project_id = projectId
  if (next.title !== previous.title) patch.title = next.title
  if (next.summary !== previous.summary) patch.summary = next.summary
  if (next.status !== previous.status) patch.status = next.status
  if (!same(next.requirement, previous.requirement)) patch.requirement = next.requirement
  if (!same(next.approach, previous.approach)) patch.approach = next.approach
  if (!same(next.checklist, previous.checklist)) patch.checklist = next.checklist
  if (!same(next.goal, previous.goal)) patch.goal = next.goal
  if (!same(next.risks, previous.risks)) patch.risks = next.risks
  if (!same(next.docs, previous.docs)) patch.docs = next.docs
  if (!same(next.open_questions, previous.open_questions)) patch.open_questions = next.open_questions
  return patch
}

/** First reason the host would refuse this draft, or null when it is sendable. */
export function validatePlanDraft(draft: PlanPackage): string | null {
  const next = sanitizePlan(draft)
  if (!next.title) return '标题不能为空'
  if (!next.requirement.restatement) return '需求复述不能为空'
  if (!next.approach.chosen) return '选中方案不能为空'
  if (next.checklist.steps.some((step) => !step.description)) return '每个步骤都要有描述'
  if (next.status === 'ready' && next.checklist.steps.length === 0) return '定稿（就绪）至少需要一步'
  if (next.goal.completion_criteria.length > 0 && !next.goal.objective) return '写了完成判据就要有目标'
  return null
}

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

export function planErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  const detail = asRecord(error)
  return str(detail.message ?? detail.error)
}

/** The host refuses a save whose `expected_revision` no longer matches. */
export function isRevisionConflict(error: unknown): boolean {
  return /revision conflict/i.test(planErrorMessage(error))
}

export function formatPlanTime(value: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
