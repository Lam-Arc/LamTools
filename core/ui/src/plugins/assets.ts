// user:“TypeError: Failed to fetch dynamically imported module”+(资源使用宿主实际后台地址，支持桌面随机端口和打包页)。
let backendOrigin: string | null = null
export function setPluginAssetBase(base: string | null): void {
  backendOrigin = base ? new URL(base).origin : null
}
/**
 * 宿主实际后台源（含桌面随机端口）。
 *
 * user:“预览器内容来源是本地文件”+(预览器的 iframe 要加载本机后台的字节接口，
 * 必须拼出带真实端口的绝对地址；打包页与开发端口的差异已经在这一处收敛过，
 * 不再另建一份"后台地址"状态，避免两处端口不同步。)
 */
export function backendOriginUrl(): string | null {
  return backendOrigin
}

export function pluginAssetUrl(path: string): string {
  return backendOrigin && path.startsWith('/api/core/plugin-system/') ? new URL(path, backendOrigin).href : path
}

// user:“Sunday也可以实现吗？去实现”+(交互运行页复用桌面实际端口，不假定开发端口)。
export function inlineVisualizationRuntimeUrl(): string {
  const path = '/api/core/inline-visualizations/runtime'
  return backendOrigin ? new URL(path, backendOrigin).href : path
}
