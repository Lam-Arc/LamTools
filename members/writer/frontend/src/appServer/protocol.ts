import { CORE_APP_SERVER_PROTOCOL_VERSION } from '@lamtools/ui'
import type { CoreAppEvent } from '@lamtools/ui'

export const WRITER_APP_SERVER_PROTOCOL_VERSION = 'writer.app_server.v1'
export const CORE_PROTOCOL_VERSION_FOR_WRITER_BASE = CORE_APP_SERVER_PROTOCOL_VERSION

export interface WriterAppEvent extends CoreAppEvent {
  event_id: string
  protocol_version?: typeof WRITER_APP_SERVER_PROTOCOL_VERSION
  seq: number
  thread_id: string
  method: string
  payload: Record<string, unknown>
  created_at: string
  turn_id?: string | null
  item_id?: string | null
  parent_item_id?: string | null
  client_message_id?: string | null
}

export type {
  CoreAppInputItem as WriterInputItem,
  CoreAppItem as WriterAppItem,
  CoreAppQueueItem as WriterAppQueueItem,
  CoreAppRequestState as WriterAppRequestState,
  CoreAppSnapshot as WriterAppSnapshot,
  CoreAppThreadStatus as WriterAppThreadStatus,
  CoreAppTurn as WriterAppTurn,
  CoreAttachmentInputItem as WriterAttachmentInputItem,
  CoreAppCommandCatalogItem as WriterCommandCatalogItem,
  CoreRuntimeItem as WriterCoreItem,
  CoreRuntimeSnapshot as WriterCoreSnapshot,
  CoreRuntimeTurn as WriterCoreTurn,
  CoreSkillInputItem as WriterSkillInputItem,
  CoreTextInputItem as WriterTextInputItem,
} from '@lamtools/ui'
