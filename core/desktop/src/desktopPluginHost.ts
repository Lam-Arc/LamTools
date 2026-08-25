import { invoke } from '@tauri-apps/api/core'

interface DesktopPluginDescriptor {
  name: string
  title: string
  entry_url: string
  window: Record<string, unknown>
}

interface PluginRequest {
  source: 'lamtools-desktop-plugin'
  id: string
  command: string
  args?: Record<string, unknown>
}

const frame = document.querySelector<HTMLIFrameElement>('#plugin-frame')
const errorRegion = document.querySelector<HTMLElement>('#host-error')

const allowedCommands = new Set([
  'start_window_dragging',
  'get_desktop_plugin_anchor',
  'set_desktop_plugin_expanded',
  'get_desktop_plugin_cursor_position',
  'set_desktop_plugin_cursor_passthrough',
  'show_main_window',
  'hide_current_window',
  'quit_app',
])

let pluginOrigin = ''

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '未知错误')
}

async function showError(error: unknown): Promise<void> {
  console.error('[desktop-plugin-host]', error)
  document.body.classList.add('has-error')
  if (errorRegion) errorRegion.textContent = `桌面插件启动失败：${errorText(error)}`
  await invoke('show_current_window').catch(() => undefined)
}

function commandArgs(message: PluginRequest): Record<string, unknown> {
  if (message.command === 'set_desktop_plugin_cursor_passthrough') {
    return {
      passthrough: message.args?.passthrough === true,
    }
  }
  if (message.command === 'set_desktop_plugin_expanded') {
    const contentWidth = Number(message.args?.contentWidth)
    const contentHeight = Number(message.args?.contentHeight)
    const viewportWidth = Number(message.args?.viewportWidth)
    const viewportHeight = Number(message.args?.viewportHeight)
    return {
      expanded: message.args?.expanded === true,
      reducedMotion: message.args?.reducedMotion === true,
      contentWidth: Number.isFinite(contentWidth) && contentWidth > 0 ? contentWidth : null,
      contentHeight: Number.isFinite(contentHeight) && contentHeight > 0 ? contentHeight : null,
      viewportWidth: Number.isFinite(viewportWidth) && viewportWidth > 0 ? viewportWidth : null,
      viewportHeight: Number.isFinite(viewportHeight) && viewportHeight > 0 ? viewportHeight : null,
    }
  }
  return {}
}

window.addEventListener('message', async (event) => {
  if (!frame?.contentWindow || event.source !== frame.contentWindow || event.origin !== pluginOrigin) return

  const message = event.data as Partial<PluginRequest> | null
  if (
    !message
    || message.source !== 'lamtools-desktop-plugin'
    || typeof message.id !== 'string'
    || typeof message.command !== 'string'
  ) return

  const response: Record<string, unknown> = {
    source: 'lamtools-desktop-host',
    id: message.id,
  }

  try {
    if (!allowedCommands.has(message.command)) throw new Error(`桌面插件命令未获授权：${message.command}`)
    response.result = await invoke(message.command, commandArgs(message as PluginRequest))
  } catch (error) {
    response.error = errorText(error)
  }

  frame.contentWindow.postMessage(response, pluginOrigin)
})

async function start(): Promise<void> {
  if (!frame) throw new Error('桌面插件宿主初始化失败')

  const apiBase = await invoke('get_api_base')
  if (typeof apiBase !== 'string' || !apiBase.startsWith('http://127.0.0.1:')) {
    throw new Error('Core API 地址无效')
  }

  const response = await fetch(`${apiBase}/api/core/desktop-plugins`, { cache: 'no-store' })
  if (!response.ok) throw new Error(`读取桌面插件失败（HTTP ${response.status}）`)

  const payload = await response.json() as { plugins?: DesktopPluginDescriptor[] }
  const plugin = payload.plugins?.[0]
  if (!plugin?.entry_url) throw new Error('没有已启用的桌面插件')

  const entryUrl = new URL(plugin.entry_url, apiBase)
  if (entryUrl.origin !== new URL(apiBase).origin) throw new Error('桌面插件入口不属于 Core')
  pluginOrigin = entryUrl.origin
  document.title = plugin.title || plugin.name

  await invoke('configure_desktop_plugin_window', { spec: plugin.window || {} })
  await new Promise<void>((resolve, reject) => {
    frame.addEventListener('load', () => resolve(), { once: true })
    frame.addEventListener('error', () => reject(new Error('桌面插件页面加载失败')), { once: true })
    frame.src = entryUrl.toString()
  })
  await invoke('show_current_window')
}

start().catch(showError)

export {}
