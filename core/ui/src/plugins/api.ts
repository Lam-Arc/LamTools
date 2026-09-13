import { bundledPluginModeLoader, bundledPluginWidgetLoader } from './bundled'
import { getWidget, listWidgets, pluginUIRegistry, registerWidget, unregisterWidgets } from './registry'
import {
  PLUGIN_WIDGET_RPC_METHODS,
  type PluginRpc,
  type PluginUIEntry,
  type PluginUIListPayload,
  type PluginWidgetEntry,
  type PluginWidgetListPayload,
  type PluginWidgetInvokeParams,
} from './types'

export async function listPluginUI(requestRpc: PluginRpc): Promise<PluginUIListPayload> {
  return await requestRpc('plugin.ui.list', {}) as PluginUIListPayload
}

function widgetEntries(payload: PluginWidgetListPayload | PluginUIListPayload): PluginWidgetEntry[] {
  const value = payload as PluginWidgetListPayload & PluginUIListPayload
  const candidates = [
    ...(Array.isArray(value.widgets) ? value.widgets : []),
    ...(Array.isArray(value.entries) ? value.entries : []),
    ...(Array.isArray(value.sidebar?.widgets) ? value.sidebar.widgets : []),
  ]
  const seen = new Set<string>()
  return candidates.flatMap((entry) => {
    if (!entry || typeof entry !== 'object') return []
    const raw = entry as PluginWidgetEntry
    const pluginId = String(raw.pluginId || raw.plugin_id || '').trim()
    const id = String(raw.id || '').trim()
    const title = String(raw.title || id).trim()
    if (!pluginId || !id || !title) return []
    const normalized: PluginWidgetEntry = {
      ...raw,
      pluginId,
      id,
      title,
      plugin_id: raw.plugin_id || pluginId,
      actions: Array.isArray(raw.actions) ? raw.actions : [],
    }
    const key = `${pluginId}:${id}`
    if (seen.has(key)) return []
    seen.add(key)
    return [normalized]
  })
}

/** List widget descriptors, retaining a legacy plugin.ui.list fallback. */
export async function listPluginWidgets(
  requestRpc: PluginRpc,
  params: Record<string, unknown> = {},
): Promise<PluginWidgetListPayload> {
  try {
    const result = await requestRpc(PLUGIN_WIDGET_RPC_METHODS.list, params) as PluginWidgetListPayload
    return { ...result, widgets: widgetEntries(result) }
  } catch (primaryError) {
    try {
      const legacy = await requestRpc('plugin.ui.list', params) as PluginUIListPayload
      return { ...legacy, widgets: widgetEntries(legacy) }
    } catch {
      throw primaryError
    }
  }
}

export async function getPluginWidget(
  requestRpc: PluginRpc,
  params: { pluginId: string; widgetId: string; projectId?: string | null; workRoot?: string | null; sessionId?: string | null },
): Promise<Record<string, unknown>> {
  return await requestRpc(PLUGIN_WIDGET_RPC_METHODS.get, {
    id: params.widgetId,
    plugin_id: params.pluginId,
    widget_id: params.widgetId,
    project_id: params.projectId ?? undefined,
    work_root: params.workRoot ?? undefined,
    session_id: params.sessionId ?? undefined,
    thread_id: params.sessionId ?? undefined,
  })
}

export async function invokePluginWidget(
  requestRpc: PluginRpc,
  params: PluginWidgetInvokeParams,
): Promise<Record<string, unknown>> {
  return await requestRpc(PLUGIN_WIDGET_RPC_METHODS.invoke, {
    id: params.widgetId,
    action: params.actionId,
    plugin_id: params.pluginId,
    widget_id: params.widgetId,
    action_id: params.actionId,
    input: params.input || {},
    project_id: params.projectId ?? undefined,
    work_root: params.workRoot ?? undefined,
    session_id: params.sessionId ?? undefined,
    thread_id: params.sessionId ?? undefined,
    confirmed: params.confirmed === true ? true : undefined,
    idempotency_key: params.idempotencyKey,
  })
}

/** Refresh the safe widget registry without loading arbitrary plugin paths. */
export async function refreshPluginUIWidgets(
  requestRpc: PluginRpc,
  params: Record<string, unknown> = {},
): Promise<PluginWidgetEntry[]> {
  const payload = await listPluginWidgets(requestRpc, params)
  const entries = widgetEntries(payload)
  const enabledPlugins = new Set(entries.map((entry) => entry.pluginId))
  for (const widget of listWidgets()) {
    if (!enabledPlugins.has(widget.pluginId)) unregisterWidgets(widget.pluginId)
  }
  for (const entry of entries) {
    const existing = getWidget(entry.id, entry.pluginId)
    const bundledLoader = entry.renderer === 'component'
      ? bundledPluginWidgetLoader(entry.pluginId, entry.id)
      : undefined
    registerWidget(entry, bundledLoader || existing?.load)
  }
  return entries
}

/** Refresh enabled plugin modes and register the bundled component loaders. */
export async function refreshPluginUIModes(requestRpc: PluginRpc): Promise<PluginUIEntry[]> {
  const payload = await listPluginUI(requestRpc)
  const entries = Array.isArray(payload.modes) ? payload.modes : []
  const enabledPlugins = new Set(entries.map((entry) => entry.pluginId))
  for (const mode of pluginUIRegistry.listModes()) {
    if (!enabledPlugins.has(mode.pluginId)) pluginUIRegistry.unregisterPlugin(mode.pluginId)
  }
  for (const entry of entries) {
    const loader = bundledPluginModeLoader(entry.pluginId, entry.id)
    if (loader) pluginUIRegistry.registerMode(entry, loader)
  }
  // Newer servers include sidebar descriptors in the same response.  Keep
  // this registration opportunistic; the host can still call the dedicated
  // plugin.widget.list endpoint when available.
  for (const entry of widgetEntries(payload)) {
    const existing = getWidget(entry.id, entry.pluginId)
    const bundledLoader = entry.renderer === 'component'
      ? bundledPluginWidgetLoader(entry.pluginId, entry.id)
      : undefined
    registerWidget(entry, bundledLoader || existing?.load)
  }
  return entries
}
