/** Workflow mode — shared types mirroring the backend runtime/workflow.py model. */

/**
 * Built-in node ids exposed by the current registry.
 *
 * The editor deliberately keeps the legacy ids in this list: old documents
 * may still contain them and must remain editable.  New/custom registry
 * entries are also valid node kinds, so the public type has an open string
 * tail instead of forcing an unknown type through the old `command` bucket.
 */
export const WORKFLOW_NODE_KINDS = [
  'model', 'agent', 'command', 'python', 'constant', 'input', 'output',
  'template', 'condition', 'merge', 'join', 'subgraph',
  // Compatibility ids.  They are hidden from the default add catalog.
  'ai', 'script', 'content', 'transform', 'branch',
] as const

export type WorkflowNodeKind = (typeof WORKFLOW_NODE_KINDS)[number] | (string & {})

export const WORKFLOW_LEGACY_NODE_KINDS = ['ai', 'script', 'content', 'transform', 'branch'] as const
export type WorkflowLegacyNodeKind = (typeof WORKFLOW_LEGACY_NODE_KINDS)[number]

export function isLegacyWorkflowNodeKind(value: unknown): value is WorkflowLegacyNodeKind {
  return (WORKFLOW_LEGACY_NODE_KINDS as readonly string[]).includes(String(value || '').trim().toLowerCase())
}
export type PortDirection = 'in' | 'out'

/** JSON-schema-like field metadata returned by workflow.object_info. */
export interface WorkflowSchemaField {
  type: string
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  options?: unknown[]
  choices?: unknown[]
  items?: WorkflowSchemaField | Record<string, unknown>
  multiline?: boolean
  [key: string]: unknown
}

/** ComfyUI-style object-info entry, kept data-only for trusted rendering. */
export interface WorkflowNodeSchema {
  name: string
  type_id?: string
  display_name?: string
  title?: string
  description?: string
  category?: string
  input?: Record<string, unknown>
  output?: Record<string, unknown>
  input_schema?: Record<string, unknown>
  output_schema?: Record<string, unknown>
  output_name?: string[]
  output_is_list?: boolean[]
  pure?: boolean
  deterministic?: boolean
  executor?: string
  plugin_id?: string
  builtin?: boolean
  /** Registry visibility metadata; legacy/deprecated entries stay loadable. */
  hidden?: boolean
  visible?: boolean
  deprecated?: boolean
  legacy?: boolean
  tags?: string[]
  keywords?: string[]
  type_version?: number
  [key: string]: unknown
}

export type WorkflowQueueStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'paused'

/** Durable queue entry returned by workflow.queue.*. */
export interface WorkflowQueueItem {
  queue_id: string
  id: string
  workflow_id: string
  workflow_name: string
  work_root: string
  thread_id: string
  run_id: string
  inputs: Record<string, unknown>
  status: WorkflowQueueStatus
  priority: number
  created_at?: string | null
  updated_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  max_steps?: number | null
  start_node?: string | null
  single_node?: string | null
  prior_values?: Record<string, unknown>
  prior_node_states?: Record<string, WorkflowNodeState>
  result?: WorkflowRunResult | null
  error?: string
  metadata?: Record<string, unknown>
}
/** Canonical status used by the editor for an individual node. */
export type NodeStateStatus = 'idle' | 'running' | 'waiting' | 'done' | 'error' | 'skipped' | 'cancelled'

/** Raw status aliases still emitted by older workflow runners. */
export type WorkflowNodeStatus = NodeStateStatus | 'completed' | 'failed' | 'success' | 'failure'

export interface WorkflowPort {
  name: string
  /** Stable graph identity; the display name may be edited without retargeting links. */
  id?: string
  type: string
  direction: PortDirection
  description?: string
  /** Schema/runtime hints retained by the V2 document adapter. */
  required?: boolean
  lazy?: boolean
  /** Constant value for ``content`` node output ports (each port carries its own). */
  value?: unknown
}

export interface WorkflowNode {
  id: string
  kind: WorkflowNodeKind
  title: string
  config: Record<string, unknown>
  ports: WorkflowPort[]
  position: { x: number; y: number }
  /** Optional canvas container relationship; absent on legacy graph nodes. */
  parent_id?: string
  /** ComfyUI/object-info type identity. Built-in ``kind`` remains the editor fallback. */
  type_id?: string
  type_version?: number
}

/** Alias used where the `WorkflowNode` name clashes with the component export. */
export type WorkflowNodeData = WorkflowNode

export interface WorkflowEdge {
  id: string
  source: string
  source_port: string
  /** Stable source port identity retained while the display name changes. */
  source_port_id?: string
  target: string
  target_port: string
  /** Stable target port identity retained while the display name changes. */
  target_port_id?: string
  /** Optional JSONPath-style field path applied to the upstream value (e.g. ``$.field``). */
  transform?: WorkflowExpression
  /** Safe expression AST or legacy string; false transmits the skip sentinel. */
  condition?: WorkflowExpression
}

export type WorkflowExpression = string | Record<string, unknown>

export interface WorkflowTrigger {
  id: string
  type: 'manual' | 'once' | 'interval' | 'calendar' | 'event'
  enabled: boolean
  name?: string
  inputs?: Record<string, unknown>
  max_runs?: number
  [key: string]: unknown
}

export interface WorkflowConcurrencyPolicy {
  key: string
  max: number
}

export interface WorkflowRateLimitPolicy {
  count: number
  window_seconds: number
}

export interface WorkflowThrottlePolicy {
  min_interval_seconds: number
}

export interface WorkflowDebouncePolicy {
  window_seconds: number
  mode: 'leading' | 'trailing'
}

export interface WorkflowPolicies extends Record<string, unknown> {
  concurrency?: WorkflowConcurrencyPolicy
  rate_limit?: WorkflowRateLimitPolicy
  throttle?: WorkflowThrottlePolicy
  debounce?: WorkflowDebouncePolicy
  priority?: number
}

export interface WorkflowInputParam {
  name: string
  type: string
  description?: string
  required: boolean
  default?: unknown
}

export interface WorkflowDef {
  /** Stable resource identity; the display name may be renamed. */
  id: string
  name: string
  description: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  input_params: WorkflowInputParam[]
  output_port: string
  exposed: boolean
  tool_name: string
  work_root: string
  /** Mermaid-style edge text (source of truth for connections in the folder layout). */
  map: string
  created_at: string
  updated_at: string
  /** Optimistic-concurrency revision; absent in legacy workflow files. */
  revision?: number | string
  /** Editor-only decorations; executable runtimes ignore this optional field. */
  canvas_elements?: import('./canvas').WorkflowCanvasElement[]
  /** Canonical V2 document returned by workflow.document.get/save. */
  document?: WorkflowDocumentV2
  triggers?: WorkflowTrigger[]
  policies?: WorkflowPolicies
}

/** Canonical, machine-readable workflow wire envelope (lamtools.workflow V2). */
export interface WorkflowDocumentV2 {
  format: 'lamtools.workflow'
  version: 2
  resource: WorkflowDocumentResource
  graph: {
    nodes: WorkflowDocumentNode[]
    links: WorkflowDocumentLink[]
  }
  interface: {
    inputs: WorkflowDocumentInterfaceInput[]
    outputs: WorkflowDocumentInterfaceOutput[]
  }
  exposure: { enabled: boolean; tool_name: string }
  canvas: WorkflowDocumentCanvas
  triggers: WorkflowTrigger[]
  policies: WorkflowPolicies
}

export interface WorkflowDocumentResource {
  id: string
  name: string
  description: string
  work_root: string
  revision: number
  created_at: string
  updated_at: string
}

export interface WorkflowDocumentNode {
  id: string
  type: { id: string; version: number }
  title: string
  ports: WorkflowDocumentPort[]
  params: Record<string, unknown>
  execution: {
    enabled: boolean
    schema_only: boolean
    cache: string
    on_error: Record<string, unknown>
    permissions: string[]
  }
}

export interface WorkflowDocumentPort {
  id: string
  name: string
  direction: PortDirection
  data_type: string
  description: string
  required: boolean
  lazy: boolean
  default?: unknown
}

export interface WorkflowDocumentLink {
  id: string
  source: { node_id: string; port_id: string }
  target: { node_id: string; port_id: string }
  transform?: WorkflowExpression
  condition?: WorkflowExpression
}

export interface WorkflowDocumentInterfaceInput {
  id: string
  name: string
  data_type: string
  description: string
  required: boolean
  default?: unknown
  target?: { node_id: string; port_id: string }
}

export interface WorkflowDocumentInterfaceOutput {
  id: string
  name: string
  data_type: string
  description: string
  source: { node_id: string; port_id: string }
}

export interface WorkflowDocumentCanvas {
  viewport: { x: number; y: number; zoom: number }
  node_views: Record<string, Record<string, unknown>>
  groups: Array<Record<string, unknown>>
  reroutes: Array<Record<string, unknown>>
  annotations: Array<Record<string, unknown>>
}

export interface WorkflowNodeState {
  node_id: string
  status: NodeStateStatus
  output?: unknown
  error?: string
  attempts: number
  /** Cache decision emitted by the runner (hit/miss/bypass). */
  cache_status?: string
  /** Content-addressed cache key, when a lookup was attempted. */
  cache_key?: string
  started_at?: string | null
  finished_at?: string | null
}

export interface WorkflowCacheFact {
  /** Canonical cache decision, normally hit/miss/bypass. */
  status?: string
  /** Explicit lookup outcome retained for consumers that need a boolean. */
  hit?: boolean
  miss?: boolean
  /** Content-addressed key used by the runner. */
  key?: string
  [key: string]: unknown
}

export type WorkflowRunStatus = 'completed' | 'failed' | 'cancelled' | 'paused'

export interface WorkflowActivation {
  id: string
  workflow_id: string
  workflow_name: string
  workflow_revision: number
  trigger_id: string
  trigger_type: string
  status: string
  next_run_at?: string | null
  run_count: number
  max_runs?: number | null
  last_error: string
  revision: number
}

export type WorkflowHumanTaskStatus = 'pending' | 'completed' | 'failed' | 'cancelled'

/** One immutable event-journal row exposed by workflow.human_task.get. */
export interface WorkflowHumanTaskAuditEvent {
  event_id: string
  sequence: number
  kind: string
  occurred_at?: string | null
  workflow_id?: string
  workflow_revision?: number
  node_id?: string
  attempt_id?: string
  payload?: Record<string, unknown>
}

/** Secret-free projected approval/wait task.  The resume token is never wire-visible. */
export interface WorkflowHumanTask {
  task_id: string
  id: string
  status: WorkflowHumanTaskStatus | string
  run_id: string
  run: string
  thread_id: string
  thread: string
  workflow_id: string
  workflow_name: string
  workflow: string
  workflow_revision: number
  revision: number
  node_id: string
  node: string
  kind: 'approval' | 'wait_event' | string
  title: string
  assignee?: string | null
  group?: string | null
  form: unknown
  due_at?: string | null
  event_type: string
  created_at?: string | null
  completed_at?: string | null
  outcome?: Record<string, unknown> | null
  work_root?: string
  audit?: WorkflowHumanTaskAuditEvent[]
}

/** Local-only status while an RPC run is in flight. */
export type WorkflowRunStatusValue = WorkflowRunStatus | 'running' | 'done' | 'error' | 'success' | 'failure'

export interface WorkflowRunResult {
  status: WorkflowRunStatus | 'running'
  output: unknown
  node_states: Record<string, WorkflowNodeState>
  values: Record<string, unknown>
  /** Per-node cache facts; preserve hit/miss/key from the runtime contract. */
  cache: Record<string, WorkflowCacheFact>
  error: string
  run_id: string
  steps_remaining: number
  started_at?: string | null
  finished_at?: string | null
}

/** Normalize node status aliases at the UI boundary. */
export function normalizeNodeStateStatus(value: unknown): NodeStateStatus {
  const status = String(value || '').trim().toLowerCase()
  if (status === 'completed' || status === 'complete' || status === 'success' || status === 'succeeded' || status === 'done') return 'done'
  if (status === 'failed' || status === 'failure' || status === 'error' || status === 'errored') return 'error'
  if (status === 'waiting') return 'waiting'
  if (status === 'in_progress' || status === 'in-progress' || status === 'queued' || status === 'pending' || status === 'active') return 'running'
  if (status === 'skipped' || status === 'skip') return 'skipped'
  if (status === 'cancelled' || status === 'canceled' || status === 'aborted') return 'cancelled'
  return 'idle'
}

/** Normalize whole-run status aliases at the UI boundary. */
export function normalizeWorkflowRunStatus(value: unknown): WorkflowRunStatus | 'running' {
  const status = String(value || '').trim().toLowerCase()
  if (status === 'done' || status === 'complete' || status === 'completed' || status === 'success' || status === 'succeeded') return 'completed'
  if (status === 'error' || status === 'errored' || status === 'failed' || status === 'failure') return 'failed'
  if (status === 'cancelled' || status === 'canceled' || status === 'aborted') return 'cancelled'
  if (status === 'paused' || status === 'suspended' || status === 'waiting') return 'paused'
  if (status === 'running' || status === 'active' || status === 'in_progress' || status === 'in-progress') return 'running'
  return 'running'
}
