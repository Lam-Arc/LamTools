import type { Message, Project, ReplyAttachment, Session } from '@/types'
import type { RuntimeActivityGroup } from '@/lib/labels'

export interface RuntimeActivity {
  id: string
  group: RuntimeActivityGroup
  displayGroup: string
  tag: string
  title: string
  subtitle: string
  detail: string
  status: 'running' | 'done' | 'failed' | 'waiting'
  createdAt: string
  completedAt: string | null
  raw: Record<string, unknown>
}

export type RuntimeBlock = {
  id: string
  kind: 'runtime'
  blockType: 'read' | 'search' | 'write' | 'command' | 'agent' | 'design-agent' | 'plan' | 'decision' | 'verify' | 'git' | 'tool'
  status: string
  title: string
  subtitle: string
  detail: string
  createdAt: string
  completedAt: string | null
  steps: Array<Record<string, unknown>>
  agentSummary?: AgentSummary
}

export type AgentSummary = {
  title: string
  task: string
  result: string
  progressLabel: string
  currentLine: AgentProgressLine | null
  selected?: string
  sections: Array<{ label: string; value: string }>
  updates: string[]
  candidates: string[]
  progress: AgentProgressLine[]
}

export type AgentProgressLine = {
  index: number
  phase: string
  status: string
  detail: string
}

export type AgentLogView = {
  title: string
  kind: 'json' | 'text'
  text: string
  rows: Array<{ key: string; value: string }>
}

export type ProjectGroup = {
  key: string
  primary: Project
  projects: Project[]
  sessions: Session[]
}

export type ProjectSessionMode = 'normal' | 'collapsed' | 'expanded'

export type ReviewMode = 'diff' | 'record'

export type DecisionView = {
  title: string
  kind: 'light' | 'plan' | 'risk'
  kindLabel: string
  reason: string
  prompt: string
  options: Array<Record<string, unknown>>
  blocking: boolean
  statusLabel: string
  plan: DecisionPlanView | null
  details: Array<{ label: string; lines: string[] }>
}

export type DecisionPlanStepView = {
  index: number
  description: string
  deliverables: string[]
  acceptance: string[]
}

export type DecisionPlanView = {
  goal: string
  shortGoal: string
  constraints: string[]
  steps: DecisionPlanStepView[]
  summary: string
}

export type ActivityGroupView = {
  group: RuntimeActivityGroup
  label: string
  status: RuntimeActivity['status']
  count: number
  items: RuntimeActivity[]
  hiddenCount: number
}

export type LifecycleView = {
  title: string
  severity: 'failed' | 'error'
  reason: string
  detail: string
  statusLabel: string
}

export type PlanProgressView = {
  total: number
  completed: number
  failed: number
  pct: number
  currentStep: string
  nextStep: string
}

export type ReplyAttachmentPreview = {
  attachment: ReplyAttachment
  title: string
  body: string
  loading: boolean
}

export type RuntimeGroup = {
  kind: 'runtime-group'
  id: string
  createdAt: string
  title: string
  blocks: RuntimeBlock[]
}

export type TranscriptItem =
  | { kind: 'message'; id: string; createdAt: string; message: Message }
  | RuntimeBlock
  | RuntimeGroup

export type DiffRow = {
  type: 'context' | 'add' | 'del'
  oldLine: number | null
  newLine: number | null
  text: string
}

export type DiffBlock =
  | { kind: 'fold'; id: string; count: number }
  | { kind: 'rows'; id: string; rows: DiffRow[] }

export type DiffFileView = {
  path: string
  oldPath: string
  blocks: DiffBlock[]
}
