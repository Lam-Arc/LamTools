import type { PluginModeLoader } from './types'

/**
 * Compile-time loaders for bundled plugin UI.
 *
 * Installed plugins receive descriptors from the backend, but their Vue
 * components are intentionally not evaluated as arbitrary runtime code in
 * the first contribution protocol. Official bundled entries opt into this
 * table and are compiled with the main UI bundle.
 */
export const bundledPluginModeLoaders: Record<string, PluginModeLoader> = {
  // Official bundled plugins are compiled with the Core UI bundle.  The
  // backend still owns discovery and enable/disable state; this table only
  // resolves the trusted local component after the descriptor is returned.
  'workflow:workflow': () => import('@lamtools/bundled-workflow-ui'),
}

export function bundledPluginModeLoader(pluginId: string, modeId: string): PluginModeLoader | undefined {
  return bundledPluginModeLoaders[`${pluginId}:${modeId}`] || bundledPluginModeLoaders[pluginId]
}
