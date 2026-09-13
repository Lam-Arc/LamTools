import type {
  PluginMode,
  PluginModeLoader,
  PluginUIEntry,
  PluginWidget,
  PluginWidgetEntry,
  PluginWidgetLoader,
} from './types'

/** Generic registry for UI modes contributed by enabled plugins. */
export class PluginUIRegistry {
  private readonly modes = new Map<string, PluginMode>()
  private readonly widgets = new Map<string, PluginWidget>()

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

  /**
   * Register a widget descriptor.  A missing loader is intentional for the
   * safe declarative `blocks` renderer; component renderers only become
   * executable when an in-process allowlisted loader is supplied.
   */
  registerWidget(entry: PluginWidgetEntry, load?: PluginWidgetLoader): PluginWidget {
    const widget: PluginWidget = { ...entry, load }
    this.widgets.set(this.key(entry.pluginId, entry.id), widget)
    return widget
  }

  getWidget(id: string, pluginId?: string): PluginWidget | undefined {
    if (pluginId) return this.widgets.get(this.key(pluginId, id))
    const matches = [...this.widgets.values()].filter((widget) => widget.id === id)
    return matches.length === 1 ? matches[0] : undefined
  }

  listWidgets(): PluginWidget[] {
    return [...this.widgets.values()].sort((a, b) => (
      (a.order ?? 0) - (b.order ?? 0)
      || `${a.pluginId}:${a.id}`.localeCompare(`${b.pluginId}:${b.id}`)
    ))
  }

  unregisterPlugin(pluginId: string): void {
    for (const [key, mode] of this.modes) {
      if (mode.pluginId === pluginId) this.modes.delete(key)
    }
    this.unregisterWidgets(pluginId)
  }

  unregisterWidgets(pluginId: string): void {
    for (const [key, widget] of this.widgets) {
      if (widget.pluginId === pluginId) this.widgets.delete(key)
    }
  }

  clear(): void {
    this.modes.clear()
    this.widgets.clear()
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

export function registerWidget(entry: PluginWidgetEntry, load?: PluginWidgetLoader): PluginWidget {
  return pluginUIRegistry.registerWidget(entry, load)
}

export function getWidget(id: string, pluginId?: string): PluginWidget | undefined {
  return pluginUIRegistry.getWidget(id, pluginId)
}

export function listWidgets(): PluginWidget[] {
  return pluginUIRegistry.listWidgets()
}

export function unregisterPlugin(pluginId: string): void {
  pluginUIRegistry.unregisterPlugin(pluginId)
}

export function unregisterWidgets(pluginId: string): void {
  pluginUIRegistry.unregisterWidgets(pluginId)
}
