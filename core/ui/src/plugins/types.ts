import type { Component } from 'vue'

export interface PluginUIEntry {
  pluginId: string
  id: string
  title: string
  entry: string
  icon?: string
  enabled?: boolean
  tools?: string[]
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
}
