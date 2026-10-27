/**
 * 插件窗口打开入口。
 *
 * user:“甚至调用 Sunday 的 API”+插件自己声明的窗口要能在桌面端真正打开，
 * 其它宿主（浏览器预览、测试环境）没有 Tauri 时安静跳过，不抛错。
 */

import { pluginAssetUrl } from '@/plugins/assets'

export interface PluginWindowTarget {
  plugin: string
  id: string
  title?: string
  url: string
  width?: number
  height?: number
}

interface TauriInvokeHost {
  invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>
}

function tauriInvoke(): TauriInvokeHost['invoke'] | null {
  if (typeof window === 'undefined') return null
  const host = (window as unknown as { __TAURI_INTERNALS__?: TauriInvokeHost })
    .__TAURI_INTERNALS__
  return typeof host?.invoke === 'function' ? host.invoke.bind(host) : null
}

/** 窗口标签只用 Tauri 允许的字符，插件名与窗口 id 拼起来保证唯一。 */
export function pluginWindowLabel(target: Pick<PluginWindowTarget, 'plugin' | 'id'>): string {
  const slug = (value: string, fallback: string): string => {
    const cleaned = value.trim().replace(/[^A-Za-z0-9_:/-]+/g, '-')
    return cleaned || fallback
  }
  return `plugin-window:${slug(target.plugin, 'plugin')}:${slug(target.id, 'window')}`
}

/** 返回 true 表示真的交给桌面端打开了窗口，false 表示当前宿主没有窗口能力。 */
export async function openPluginWindow(target: PluginWindowTarget): Promise<boolean> {
  const invoke = tauriInvoke()
  if (!invoke || !target.url) return false
  // user:“点击之后没反应”+(宿主的 plugin.system.ui 给的是 /api/... 相对地址，
  // Tauri 的 Url::parse 只认绝对地址，直接传会失败；这里按后台实际地址补全。)
  const url = pluginAssetUrl(target.url)
  await invoke('open_plugin_window', {
    label: pluginWindowLabel(target),
    url,
    title: target.title || target.id,
    width: target.width ?? 420,
    height: target.height ?? 620,
  })
  return true
}
