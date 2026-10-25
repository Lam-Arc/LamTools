

declare interface Window {
  LamToolsPluginRPC?: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}
