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
  core?: CoreRuntimeSnapshot
  status?: CoreAppThreadStatus
  history_page?: CoreHistoryPage
}

export interface CoreHistoryPage {
  char_limit: number
  character_count: number
  turn_limit?: number
  turn_count?: number
  item_count: number
  total_items: number
  has_more: boolean
  next_before_item_id?: string | null
  next_before_seq?: number | null
}

export type CoreAppThreadStatus = 'idle' | 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled'

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
 * Model and thinking options remain turn-scoped; permission fields record the
 * initial/compatibility state and are overlaid from the live session before
 * dispatching or continuing work.
 */
export interface CoreAppRuntimeSnapshot {
  permission_preset?: 'ask' | 'auto' | 'full_access'
  active_tier?: 'read_only' | 'limited_edit' | 'full_edit' | null
  tier_tools?: Record<string, string[]> | null
  approval_policy?: 'require' | 'auto_approve'
  allow_access_outside_workdir?: boolean
  active_mode?: string | null
  model_id?: string | null
  reasoning_level?: 'off' | 'light' | 'high' | 'max'
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
  context_metrics?: Record<string, unknown>
  runtime_snapshot?: CoreAppRuntimeSnapshot
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
  status?: CoreAppThreadStatus
}

export interface CoreRuntimeTurn {
  turn_id: string
  status: string
  items?: string[]
  usage?: Record<string, unknown>
  /** Estimated context pressure and compaction state, never billing usage. */
  context_metrics?: Record<string, unknown>
  runtime_snapshot?: CoreAppRuntimeSnapshot
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
