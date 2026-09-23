import type { Component } from 'vue'
import type {
  RightSidebarWidgetAction,
  RightSidebarWidgetSnapshot,
  PluginWidgetEntry,
} from '../right-sidebar/types'

export type {
  PluginWidgetEntry,
  RightSidebarWidgetAction,
  RightSidebarWidgetSnapshot,
} from '../right-sidebar/types'

export interface PluginUIEntry {
  pluginId: string
  id: string
  title: string
  entry: string
  icon?: string
  enabled?: boolean
  tools?: string[]
  /**
   * Host-declared capabilities for this mode.  An absent list means the host
   * makes no claim, so the UI keeps every surface available; an empty list
   * means the host supports none of them.
   */
  capabilities?: string[]
}

export interface PluginMode extends PluginUIEntry {
  load: PluginModeLoader
}

export type PluginModeLoader = () => Promise<Component | { default: Component }>

export type PluginRpc = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

export interface PluginUIListPayload {
  modes?: PluginUIEntry[]
  views?: PluginUIEntry[]
  widgets?: PluginWidgetEntry[]
  sidebar?: { widgets?: PluginWidgetEntry[] }
}

/** A descriptor plus an optional trusted, in-process component loader. */
export interface PluginWidget extends PluginWidgetEntry {
  load?: PluginWidgetLoader
  /** A snapshot may be supplied by a plugin-mode surface before RPC refresh. */
  snapshot?: RightSidebarWidgetSnapshot | null
}

export type PluginWidgetLoader = () => Promise<Component | { default: Component }>

export interface PluginWidgetListPayload {
  widgets?: PluginWidgetEntry[]
  sidebar?: { widgets?: PluginWidgetEntry[] }
  entries?: PluginWidgetEntry[]
}

export const PLUGIN_WIDGET_RPC_METHODS = {
  list: 'plugin.widget.list',
  get: 'plugin.widget.get',
  invoke: 'plugin.widget.invoke',
} as const

export type PluginWidgetRpcMethod = (typeof PLUGIN_WIDGET_RPC_METHODS)[keyof typeof PLUGIN_WIDGET_RPC_METHODS]

export interface PluginWidgetInvokeParams {
  pluginId: string
  widgetId: string
  actionId: string
  input?: Record<string, unknown>
  projectId?: string | null
  workRoot?: string | null
  sessionId?: string | null
  confirmed?: boolean
  idempotencyKey?: string
}

// Keep this import visible in generated declaration output for plugin SDK
// consumers that use the action type without importing the right-sidebar path.
export type { RightSidebarWidgetAction as PluginWidgetAction }
