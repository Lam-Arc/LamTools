import { bundledPluginModeLoader } from './bundled'
import { pluginUIRegistry } from './registry'
import type { PluginRpc, PluginUIEntry, PluginUIListPayload } from './types'

export async function listPluginUI(requestRpc: PluginRpc): Promise<PluginUIListPayload> {
  return await requestRpc('plugin.ui.list', {}) as PluginUIListPayload
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
  return entries
}
