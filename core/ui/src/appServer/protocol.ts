export const CORE_APP_SERVER_PROTOCOL_VERSION = 'core.app_server.v1'

export interface CoreAppEvent {
  event_id: string
  protocol_version?: string
  seq: number
  thread_id: string
  method: string
  payload: Record<string, unknown>
  created_at: string
  turn_id?: string | null
  item_id?: string | null
  parent_item_id?: string | null
  client_message_id?: string | null
  workspace_id?: string
  entity_type?: string
  entity_id?: string
  event_seq?: number
  revision?: number
  event_type?: string
  transient?: boolean
}

export interface CoreAppSnapshot {
  thread_id: string
  snapshot_seq: number
  revision?: number
  seen_event_ids?: string[]
  turns?: Record<string, CoreAppTurn>
  items?: Record<string, CoreAppItem>
  item_order?: string[]
  queue?: CoreAppQueueItem[]
  requests?: Record<string, CoreAppRequestState>
  artifacts?: Record<string, Record<string, unknown>>
  /** Member names/session ids whose projected timeline was deleted. */
  deleted_agents?: Record<string, boolean>
  /** Decision pool, ordered by the server-assigned sequence. */
  decisions?: CoreAppInteraction[]
  interactions?: CoreAppInteraction[]
  core?: CoreRuntimeSnapshot
  status?: CoreAppThreadStatus
  history_page?: CoreHistoryPage
}

export interface CoreHistoryPage {
  /** 只作展示的度量：本页声明的字符预算。分页以**完整回合**为单位（turn_limit），
   *  字符数不参与裁剪、也不构成体积护栏——回合不会被切开，超大回合照原样整回下发。 */
  char_limit: number
  /** 只作展示的度量：本页实测字符数；同样不参与裁剪、不设上限。 */
  character_count: number
  turn_limit?: number
  turn_count?: number
  item_count: number
  total_items: number
  has_more: boolean
  next_before_item_id?: string | null
  next_before_seq?: number | null
}

export type CoreAppThreadStatus = 'idle' | 'running' | 'waiting' | 'paused' | 'completed' | 'failed' | 'cancelled'

export interface CoreTextInputItem {
  type: 'text'
  text: string
}

export interface CoreAttachmentInputItem {
  type: 'attachment'
  attachment_id: string
  filename?: string
  mime_type?: string
  preview_type?: string
  size?: number
}

export interface CoreSkillInputItem {
  type: 'skill'
  name: string
  source_text?: string
}

export type CoreAppInputItem = CoreTextInputItem | CoreAttachmentInputItem | CoreSkillInputItem

/**
 * Runtime configuration captured when a turn or queue item is accepted.
 * The model stays turn-scoped. Permission fields record the initial state and
 * are overlaid from the live session before dispatching or continuing work;
 * mode, thinking level, and the shallow-thinking toggle follow the session's
 * composer group and may change at the turn's next step.
 */
export interface CoreAppRuntimeSnapshot {
  permission_preset?: 'ask' | 'auto' | 'full_access'
  active_tier?: 'read_only' | 'limited_edit' | 'full_edit' | null
  tier_tools?: Record<string, string[]> | null
  approval_policy?: 'require' | 'auto_approve'
  allow_access_outside_workdir?: boolean
  active_mode?: string | null
  model_id?: string | null
  reasoning_level?: 'off' | 'light' | 'medium' | 'high' | 'xhigh' | 'max'
  thinking_enabled?: boolean
  thinking_budget?: number
  reasoning_effort?: string
  shallow_thinking_enabled?: boolean
  context_window_tokens?: number
  max_tokens?: number
  temperature?: number
  compact_trigger_tokens?: number
  compact_limit_tokens?: number
  [key: string]: unknown
}

export interface CoreAppCommandCatalogItem {
  name: string
  title?: string
  description?: string
  icon?: string
  source?: 'core' | 'member' | string
  action?: 'insert_token' | 'run_action' | 'expand_on_send' | string
  kind?: 'action' | 'skill' | string
  accepts_args?: boolean
}

export interface CoreAppTurn {
  turn_id: string
  status: string
  seq?: number
  last_seq?: number
  items: string[]
  created_at?: string
  input?: CoreAppInputItem[] | unknown
  /** Provider-reported usage; absent token fields mean the provider did not report them. */
  usage?: Record<string, unknown>
  /** Estimated context pressure and compaction state, never billing usage. */
  usage_calls?: Array<{ id: string; seq: number; parent_item_id?: string | null; usage: Record<string, unknown> }>
  child_context_metrics?: Record<string, Record<string, unknown>>
  context_metrics?: Record<string, unknown>
  runtime_snapshot?: CoreAppRuntimeSnapshot
  /**
   * The main agent is holding this turn open for background members (the
   * harness wait), not working itself. Authoritative signal for the quiet
   * "main stopped, sub-agents still running" state; the paired report event
   * clears it.
   */
  waiting_on_members?: boolean
  /** Names of the members the turn is currently waiting on. */
  running_members?: string[]
  [key: string]: unknown
}

export interface CoreAppItem {
  item_id: string
  turn_id?: string | null
  parent_item_id?: string | null
  type?: string
  status?: string
  content?: unknown
  deltas?: unknown[]
  seq?: number
  last_seq?: number
  last_method?: string
  tool_name?: string
  arguments?: unknown
  request_id?: string
  [key: string]: unknown
}

export interface CoreAppQueueItem {
  queue_item_id: string
  status?: string
  mode?: string
  input?: CoreAppInputItem[] | unknown
  seq?: number
  last_method?: string
  runtime_snapshot?: CoreAppRuntimeSnapshot
  [key: string]: unknown
}

export interface CoreAppRequestState {
  request_id: string
  status: string
  item_id?: string | null
  turn_id?: string | null
  decision?: string | null
  guidance?: string | null
  seq?: number
  [key: string]: unknown
}

export interface CoreAppInteractionOption {
  id?: string
  label?: string
  description?: string
  response?: string
}

export interface CoreAppInteraction {
  interaction_id: string
  request_id?: string
  turn_id?: string
  run_id?: string
  scope?: string
  kind?: string
  status?: string
  /** appearing | processing | ending — the decision-pool lifecycle. */
  lifecycle?: string
  /** Stable hash identity for cross-window dedupe and event replay. */
  decision_id?: string
  /** Delivery order inside the pool; updates never change it. */
  sequence?: number
  project_id?: string
  agent_name?: string
  agent_session_id?: string
  delivered_by?: string
  tool_call_id?: string
  title?: string
  body?: string
  context?: string
  options?: CoreAppInteractionOption[]
  expires_at_ms?: number
  answer?: Record<string, unknown> | null
  metadata?: Record<string, unknown>
}

export interface CoreRuntimeSnapshot {
  thread_id: string
  snapshot_seq: number
  revision?: number
  seen_event_ids?: string[]
  turns?: Record<string, CoreRuntimeTurn>
  items?: Record<string, CoreRuntimeItem>
  item_order?: string[]
  requests?: Record<string, CoreAppRequestState>
  artifacts?: Record<string, Record<string, unknown>>
  /** Open/processing decisions, including cards outside the rendered window. */
  interactions?: CoreAppInteraction[]
  /** Decision pool (the same ordered list under its canonical name). */
  decisions?: CoreAppInteraction[]
  deleted_agents?: Record<string, boolean>
  status?: CoreAppThreadStatus
}

export interface CoreRuntimeTurn {
  turn_id: string
  status: string
  items?: string[]
  usage?: Record<string, unknown>
  /** Estimated context pressure and compaction state, never billing usage. */
  usage_calls?: Array<{ id: string; seq: number; parent_item_id?: string | null; usage: Record<string, unknown> }>
  child_context_metrics?: Record<string, Record<string, unknown>>
  context_metrics?: Record<string, unknown>
  runtime_snapshot?: CoreAppRuntimeSnapshot
  /** See `CoreAppTurn.waiting_on_members`. */
  waiting_on_members?: boolean
  /** See `CoreAppTurn.running_members`. */
  running_members?: string[]
  [key: string]: unknown
}

export interface CoreRuntimeItem {
  item_id: string
  turn_id?: string | null
  parent_item_id?: string | null
  kind?: string
  last_kind?: string
  status?: string
  content?: string
  deltas?: unknown[]
  /** Thread-global event seq anchor (envelope seq, NOT the batch-relative payload seq). */
  seq?: number
  payload?: Record<string, unknown>
  artifacts?: Record<string, unknown>[]
  usage?: Record<string, unknown>
  [key: string]: unknown
}
