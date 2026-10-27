// user:“TypeError: Failed to fetch dynamically imported module”+(资源使用宿主实际后台地址，支持桌面随机端口和打包页)。
let backendOrigin: string | null = null
export function setPluginAssetBase(base: string | null): void {
  backendOrigin = base ? new URL(base).origin : null
}
export function pluginAssetUrl(path: string): string {
  return backendOrigin && path.startsWith('/api/core/plugin-system/') ? new URL(path, backendOrigin).href : path
}

// user:“Sunday也可以实现吗？去实现”+(交互运行页复用桌面实际端口，不假定开发端口)。
export function inlineVisualizationRuntimeUrl(): string {
  const path = '/api/core/inline-visualizations/runtime'
  return backendOrigin ? new URL(path, backendOrigin).href : path
}
