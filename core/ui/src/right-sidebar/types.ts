import type { Component, ComputedRef, Ref } from 'vue'

/** The persistence payload for one right-sidebar scope. */
export interface RightSidebarLayoutState {
  order: string[]
  visible: Record<string, boolean>
  collapsed: Record<string, boolean>
}

export type RightSidebarModuleStatus = 'ready' | 'loading' | 'error' | 'disabled'

/**
 * A host module definition.  The definition is intentionally data-first: a
 * plugin may contribute a descriptor/snapshot, while executable Vue code must
 * come from a trusted in-process loader.
 */
export interface RightSidebarModuleDefinition {
  id: string
  title: string
  icon?: Component
  description?: string
  order?: number
  defaultVisible?: boolean
  defaultCollapsed?: boolean
  status?: RightSidebarModuleStatus
  error?: string
  disabledReason?: string
  component?: Component
  componentProps?: Record<string, unknown>
  widget?: PluginWidgetEntry
  /** Optional asynchronous loader registered by the host/SDK allowlist. */
  load?: RightSidebarModuleLoader
  /** A backend snapshot rendered by the safe declarative renderer. */
  snapshot?: RightSidebarWidgetSnapshot | null
  /** Descriptor-owned actions are invoked through the backend facade. */
  actions?: RightSidebarWidgetAction[]
  pluginId?: string
  modeId?: string
}

export type RightSidebarModuleLoader = () => Promise<Component | { default: Component }>

export interface RightSidebarModuleContext {
  module: RightSidebarModuleDefinition
  projectId: string | null
  modeId?: string | null
  requestRpc?: RightSidebarRpc
}

export type RightSidebarRpc = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

/** The bounded JSON snapshot protocol exposed by plugin.widget.*. */
export type RightSidebarWidgetState = 'ok' | 'warning' | 'error' | 'busy' | 'disabled'

export interface RightSidebarWidgetSnapshot {
  schemaVersion?: number
  schema_version?: number
  state?: RightSidebarWidgetState
  status?: string
  message?: string
  blocks?: RightSidebarWidgetBlock[]
  actions?: RightSidebarWidgetAction[]
  [key: string]: unknown
}

export type RightSidebarWidgetBlock =
  | RightSidebarWidgetTextBlock
  | RightSidebarWidgetStatusBlock
  | RightSidebarWidgetMetricBlock
  | RightSidebarWidgetListBlock
  | RightSidebarWidgetProgressBlock

export interface RightSidebarWidgetTextBlock {
  type: 'text'
  text?: string
  label?: string
  value?: string | number | boolean | null
}

export interface RightSidebarWidgetStatusBlock {
  type: 'status'
  label?: string
  value?: string
  state?: RightSidebarWidgetState
}

export interface RightSidebarWidgetMetricBlock {
  type: 'metric'
  label?: string
  value?: string | number | boolean | null
  detail?: string
}

export interface RightSidebarWidgetListBlock {
  type: 'list'
  label?: string
  items?: Array<string | number | { label?: string; value?: string | number | boolean | null; detail?: string }>
}

export interface RightSidebarWidgetProgressBlock {
  type: 'progress'
  label?: string
  value?: number
  max?: number
  detail?: string
}

export interface RightSidebarWidgetAction {
  id: string
  title: string
  operation?: string
  inputSchema?: Record<string, unknown>
  input_schema?: Record<string, unknown>
  dangerous?: boolean
  mutates?: boolean
}

/** Backend descriptor returned by plugin.ui.list / plugin.widget.list. */
export interface PluginWidgetEntry {
  pluginId: string
  plugin_id?: string
  id: string
  title: string
  entry?: string
  icon?: string
  renderer?: 'blocks' | 'component' | string
  scope?: 'global' | 'workspace' | 'session' | string
  order?: number
  modeId?: string
  mode_id?: string
  snapshotOperation?: string
  snapshot_operation?: string
  hasSnapshot?: boolean
  actions?: RightSidebarWidgetAction[]
  snapshot?: RightSidebarWidgetSnapshot | null
  enabled?: boolean
  status?: RightSidebarModuleStatus
  error?: string
}

export interface PluginWidgetListPayload {
  widgets?: PluginWidgetEntry[]
  sidebar?: { widgets?: PluginWidgetEntry[] }
  entries?: PluginWidgetEntry[]
}

/** Optional plugin-side contribution for a mode already mounted in-process. */
export interface RightSidebarPluginContribution {
  id: string
  title: string
  icon?: Component
  defaultVisible?: boolean
  defaultCollapsed?: boolean
  status?: RightSidebarModuleStatus
  error?: string
  component?: Component
  componentProps?: Record<string, unknown>
  snapshot?: RightSidebarWidgetSnapshot | null
  actions?: RightSidebarWidgetAction[]
  order?: number
}

export interface RightSidebarLayoutController {
  layout: Ref<RightSidebarLayoutState>
  activeProjectId: Ref<string | null> | ComputedRef<string | null>
  isProjectScope: Ref<boolean> | ComputedRef<boolean>
  setProject: (projectId: string | null) => void
  reset: () => void
  setVisible: (moduleId: string, visible: boolean) => void
  toggleVisible: (moduleId: string) => void
  setCollapsed: (moduleId: string, collapsed: boolean) => void
  toggleCollapsed: (moduleId: string) => void
  move: (moduleId: string, direction: -1 | 1) => void
  reorder: (moduleIds: string[]) => void
  save: () => void
}
