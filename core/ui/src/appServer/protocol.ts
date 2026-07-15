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
  transient?: boolean
}

export interface CoreAppSnapshot {
  thread_id: string
  snapshot_seq: number
  seen_event_ids?: string[]
  turns?: Record<string, CoreAppTurn>
  items?: Record<string, CoreAppItem>
  item_order?: string[]
  queue?: CoreAppQueueItem[]
  requests?: Record<string, CoreAppRequestState>
  artifacts?: Record<string, Record<string, unknown>>
  core?: CoreRuntimeSnapshot
  status?: CoreAppThreadStatus
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

export interface CoreAppCommandCatalogItem {
  name: string
  title?: string
  description?: string
  icon?: string
  source?: 'core' | 'member' | string
  action?: 'insert_token' | 'run_action' | 'expand_on_send' | string
  accepts_args?: boolean
}

export interface CoreAppTurn {
  turn_id: string
  status: string
  seq?: number
  last_seq?: number
  items: string[]
  input?: CoreAppInputItem[] | unknown
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
  payload?: Record<string, unknown>
  artifacts?: Record<string, unknown>[]
  usage?: Record<string, unknown>
  [key: string]: unknown
}
