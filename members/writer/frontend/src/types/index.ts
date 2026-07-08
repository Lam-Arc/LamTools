// --- Project ---
export interface Project {
  id: string
  name: string
  work_root: string
  agents_md: string | null
  config: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ProjectCreate {
  name?: string
  work_root?: string
}

export interface ProjectUpdate {
  name?: string
  work_root?: string
  agents_md?: string
  config?: Record<string, unknown>
}

// --- Session ---
export interface Session {
  id: string
  title: string
  work_root: string
  branch: string | null
  phase: string
  mode: string
  status: string
  lifecycle?: Record<string, unknown> | null
  project_id: string | null
  created_at: string
  updated_at: string
}

export interface SessionCreate {
  title?: string
  work_root?: string
  mode?: string
  project_id?: string
}

export interface SessionUpdate {
  title?: string
  mode?: string
  work_root?: string
  project_id?: string
}

export interface SessionForkOptions {
  after_turn_id?: string
  isolated_worktree?: boolean
  title?: string
}

export interface SessionRollbackResult {
  status: string
  session_id: string
  target_turn_id: string
  rolled_back_turn_ids: string[]
  snapshot?: Record<string, unknown>
  restore?: {
    status: string
    source: string
    ref: string | null
    checkpoint?: string | null
    message: string
  }
  message: string
}

// --- Message ---
export interface Message {
  id: string
  session_id: string
  role: string
  content: string | null
  parts: Record<string, unknown> | null
  created_at: string
}

export interface ReplyAttachment {
  id: string
  title?: string
  label?: string
  filename?: string
  kind?: string
  source?: string
  agent_name?: string | null
  preview?: string
  preview_type?: string
  mime_type?: string
  size?: number
  runtime_event_id?: string | null
  content?: string
  metadata?: Record<string, unknown>
  created_at?: string
}

export type Attachment = ReplyAttachment & {
  session_id: string
  project_id?: string | null
  message_id?: string | null
  source: string
  filename: string
  mime_type: string
  size: number
  preview_type: string
  metadata?: Record<string, unknown>
  created_at: string
}

export interface AttachmentPreview {
  id: string
  filename: string
  preview_type: string
  mime_type: string
  text: string | null
}

// --- Config: Provider ---
export interface Provider {
  id: string
  name: string
  api_type: string
  base_url: string
  api_key: string // masked by backend: "abcd...efgh"
  is_default: boolean
  extra: Record<string, unknown> | null
  has_api_key: boolean
  created_at: string
  updated_at: string
}

export interface ProviderCreate {
  name: string
  api_type?: string
  base_url: string
  api_key: string
  extra?: Record<string, unknown>
}

export type { WriterQueuedInput } from '../runtime/queue'
export type {
  WriterCommandCatalogItem,
  WriterSkillInputItem,
} from '../appServer/protocol'

export interface ProviderUpdate {
  name?: string
  api_type?: string
  base_url?: string
  api_key?: string
  extra?: Record<string, unknown> | null
}

// --- Config: Model ---
export interface Model {
  id: string
  provider_id: string
  model_id: string
  display_name: string
  context_window: number
  max_output_tokens: number
  thinking_supported: boolean
  thinking_budget: number
  temperature: number
  is_default: boolean
  extra: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ModelCreate {
  provider_id: string
  model_id: string
  display_name?: string
  context_window?: number
  max_output_tokens?: number
  thinking_supported?: boolean
  thinking_budget?: number
  temperature?: number
  extra?: Record<string, unknown>
}

export interface ModelUpdate {
  provider_id?: string
  model_id?: string
  display_name?: string
  context_window?: number
  max_output_tokens?: number
  thinking_supported?: boolean
  thinking_budget?: number
  temperature?: number
  extra?: Record<string, unknown> | null
}

export interface ResolvedConfig {
  provider: Provider
  model: Model
  task_type: string
  matched_rule: boolean
}

export interface AgentCapability {
  name: string
  description: string
  aliases: string[]
  modes: string[]
  capabilities: string[]
  can_parallel: boolean
  can_call_agents: boolean
  max_depth: number
  enabled: boolean
}

export interface SubAgentDefinition {
  name: string
  description: string
  role: string
  developer_instructions: string
  tools: string[]
  model: string
  max_tool_rounds: number
  aliases: string[]
  source: string
  enabled: boolean
}

export interface SubAgentDefinitionUpdate {
  name: string
  description: string
  role: string
  developer_instructions: string
  tools: string[]
  model?: string
  max_tool_rounds: number
  aliases?: string[]
}

export interface AgentBranch {
  branch: string
  head: string | null
  worktree: string
  dirty: boolean
  files: string[]
}

export interface ToolCapability {
  name: string
  description: string
  permission: string
  permission_group?: string
  approval_policy?: string
  enabled: boolean
}

export interface RuntimeCapabilities {
  agents: AgentCapability[]
  subagents: SubAgentDefinition[]
  tools: ToolCapability[]
  command_policies?: Record<string, string>
}

export interface AdapterProfile {
  id: string
  label: string
  protocol: string
  match_base_url: string[]
  endpoint: string | null
}

export interface AppSetting {
  namespace: string
  value: Record<string, unknown>
  updated_at: string | null
}

// --- Git Graph ---
export interface GitVersionCommit {
  sha: string
  message: string
  timestamp: string
  author: string
}

export interface GitVersionLane {
  branch: string
  is_current: boolean
  commits: GitVersionCommit[]
}

export interface GitVersionGraph {
  current_branch: string
  head: string
  lanes: GitVersionLane[]
}

export interface ChangedFile {
  path: string
  additions: number | null
  deletions: number | null
  binary: boolean
}

export interface SessionChanges {
  files: ChangedFile[]
  total_additions: number
  total_deletions: number
  diff_stat: string
  diff: string
  source: string
  ref: string | null
}

export interface SessionCheckpoint {
  label: string
  reason: string
  branch: string | null
  head: string | null
  commit: string | null
  base_head?: string | null
  storage?: string | null
  paths: string[]
  allow_empty: boolean
  created_at: string | null
}

export interface CommitReview {
  id: string
  status: string
  title: string
  summary: string
  how_to_review: string
  self_check: string
  commit_message: string
  files: ChangedFile[]
  total_additions: number
  total_deletions: number
  source: string
  ref: string | null
  commit: string | null
  feedback: string
  created_at: string
  updated_at: string
}

export interface CommitReviewDecision {
  action: 'approve' | 'request_changes' | 'postpone'
  feedback?: string
  commit_message?: string | null
}

// --- Chat ---
export interface ChatRequest {
  message: string
  work_root?: string
  mode?: string
  quality_mode?: WriterMode
  attachment_ids?: string[]
  thinking_enabled?: boolean
  thinking_budget?: number
  shallow_thinking_enabled?: boolean
  model_id?: string  // Per-request model override
}

// --- Enums / Literals ---
export type WriterInteractionMode = 'EXECUTE'

export type WriterMode = 'auto' | 'toy' | 'low' | 'medium' | 'high' | 'crazy'

export type WriterStepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

// --- Activity log entry ---
export interface ActivityEntry {
  kind: string
  text: string
  at: string
}
