import type { PluginMode, PluginModeLoader, PluginUIEntry } from './types'

/** Generic registry for UI modes contributed by enabled plugins. */
export class PluginUIRegistry {
  private readonly modes = new Map<string, PluginMode>()

  registerMode(entry: PluginUIEntry, load: PluginModeLoader): PluginMode {
    const mode: PluginMode = { ...entry, load }
    this.modes.set(this.key(entry.pluginId, entry.id), mode)
    return mode
  }

  getMode(id: string, pluginId?: string): PluginMode | undefined {
    if (pluginId) return this.modes.get(this.key(pluginId, id))
    const matches = [...this.modes.values()].filter((mode) => mode.id === id)
    return matches.length === 1 ? matches[0] : undefined
  }

  listModes(): PluginMode[] {
    return [...this.modes.values()].sort((a, b) => (
      `${a.pluginId}:${a.id}`.localeCompare(`${b.pluginId}:${b.id}`)
    ))
  }

  unregisterPlugin(pluginId: string): void {
    for (const [key, mode] of this.modes) {
      if (mode.pluginId === pluginId) this.modes.delete(key)
    }
  }

  clear(): void {
    this.modes.clear()
  }

  private key(pluginId: string, id: string): string {
    return `${pluginId}:${id}`
  }
}

export const pluginUIRegistry = new PluginUIRegistry()

export function registerMode(entry: PluginUIEntry, load: PluginModeLoader): PluginMode {
  return pluginUIRegistry.registerMode(entry, load)
}

export function getMode(id: string, pluginId?: string): PluginMode | undefined {
  return pluginUIRegistry.getMode(id, pluginId)
}

export function listModes(): PluginMode[] {
  return pluginUIRegistry.listModes()
}

export function unregisterPlugin(pluginId: string): void {
  pluginUIRegistry.unregisterPlugin(pluginId)
}
