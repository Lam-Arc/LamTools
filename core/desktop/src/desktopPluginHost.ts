import { invoke } from '@tauri-apps/api/core'
import type { Event } from '@tauri-apps/api/event'
import { getCurrentWebview } from '@tauri-apps/api/webview'
import type { DragDropEvent } from '@tauri-apps/api/webview'
import { getCurrentWindow } from '@tauri-apps/api/window'

interface DesktopPluginDescriptor {
  name: string
  title: string
  entry_url: string
  window: Record<string, unknown>
  fileDrop?: boolean
}

interface PluginRequest {
  source: 'lamtools-desktop-plugin'
  id: string
  command: string
  args?: Record<string, unknown>
}

interface DesktopDropSummary {
  dropId: string
  files: Array<{ name: string }>
}

const DESKTOP_PET_PLUGIN_NAME = 'emotion-ball-pet'

const frame = document.querySelector<HTMLIFrameElement>('#plugin-frame')
const errorRegion = document.querySelector<HTMLElement>('#host-error')

const allowedCommands = new Set([
  'start_window_dragging',
  'save_desktop_plugin_position',
  'get_desktop_plugin_dock_zone',
  'set_desktop_plugin_dock',
  'get_desktop_plugin_anchor',
  'set_desktop_plugin_expanded',
  'set_desktop_plugin_view_mode',
  'get_desktop_plugin_view_mode_transition',
  'get_desktop_plugin_cursor_position',
  'set_desktop_plugin_cursor_passthrough',
  'import_dropped_files',
  'discard_dropped_files',
  'show_main_window',
  'hide_current_window',
  'quit_app',
])

let pluginOrigin = ''
let fileDropEnabled = false
let unlistenFileDrop: (() => void) | undefined
let unlistenWindowMoved: (() => void) | undefined
let placementSaveTimer: number | undefined
let fileDropRequestGeneration = 0
const registeredDropIds = new Set<string>()

window.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && ['+', '-', '=', '0'].includes(event.key)) {
    event.preventDefault()
  }
})
window.addEventListener('wheel', (event) => {
  if (event.ctrlKey || event.metaKey) event.preventDefault()
}, { passive: false })

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '未知错误')
}

function postPluginEvent(message: Record<string, unknown>): boolean {
  if (!frame?.contentWindow || !pluginOrigin) return false
  frame.contentWindow.postMessage({ source: 'lamtools-desktop-host', ...message }, pluginOrigin)
  return true
}

async function discardRegisteredDrop(dropId: string): Promise<void> {
  if (!dropId || !registeredDropIds.has(dropId)) return
  try {
    await invoke('discard_desktop_plugin_drop', { dropId })
    registeredDropIds.delete(dropId)
  } catch (error) {
    console.warn('[desktop-plugin-host] discarding desktop drop failed:', error)
  }
}

async function handleFileDropEvent(event: Event<DragDropEvent>): Promise<void> {
  if (!fileDropEnabled) return
  if (event.payload.type === 'enter') {
    postPluginEvent({ type: 'file-drag-enter' })
  } else if (event.payload.type === 'leave') {
    postPluginEvent({ type: 'file-drag-leave' })
  } else if (event.payload.type === 'drop') {
    postPluginEvent({ type: 'file-drag-leave' })
    const generation = ++fileDropRequestGeneration
    try {
      const drop = await invoke<DesktopDropSummary>('register_desktop_plugin_drop', {
        paths: event.payload.paths,
      })
      registeredDropIds.add(drop.dropId)
      if (generation !== fileDropRequestGeneration) {
        await discardRegisteredDrop(drop.dropId)
        return
      }
      const delivered = postPluginEvent({ type: 'files-dropped', dropId: drop.dropId, files: drop.files })
      if (!delivered) await discardRegisteredDrop(drop.dropId)
    } catch (error) {
      if (generation === fileDropRequestGeneration) {
        postPluginEvent({ type: 'file-drop-error', message: errorText(error) })
      }
    }
  }
}

async function listenForFileDrops(): Promise<void> {
  if (!fileDropEnabled) return
  unlistenFileDrop = await getCurrentWebview().onDragDropEvent(handleFileDropEvent)
}

function scheduleDesktopPluginPlacementSave(): void {
  if (placementSaveTimer !== undefined) window.clearTimeout(placementSaveTimer)
  placementSaveTimer = window.setTimeout(() => {
    placementSaveTimer = undefined
    void invoke('save_desktop_plugin_position').catch((error) => {
      console.warn('[desktop-plugin-host] saving desktop plugin position failed:', error)
    })
  }, 280)
}

async function listenForWindowMoves(): Promise<void> {
  unlistenWindowMoved = await getCurrentWindow().onMoved(() => {
    scheduleDesktopPluginPlacementSave()
  })
}

window.addEventListener('beforeunload', () => {
  fileDropRequestGeneration += 1
  unlistenFileDrop?.()
  unlistenFileDrop = undefined
  unlistenWindowMoved?.()
  unlistenWindowMoved = undefined
  if (placementSaveTimer !== undefined) window.clearTimeout(placementSaveTimer)
  placementSaveTimer = undefined
  registeredDropIds.forEach((dropId) => {
    void discardRegisteredDrop(dropId)
  })
  void invoke('save_desktop_plugin_position').catch(() => undefined)
})

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
  if (message.command === 'get_desktop_plugin_cursor_position') {
    const viewportWidth = Number(message.args?.viewportWidth)
    const viewportHeight = Number(message.args?.viewportHeight)
    return {
      viewportWidth: Number.isFinite(viewportWidth) && viewportWidth > 0 ? viewportWidth : null,
      viewportHeight: Number.isFinite(viewportHeight) && viewportHeight > 0 ? viewportHeight : null,
    }
  }
  if (message.command === 'set_desktop_plugin_view_mode') {
    const mode = String(message.args?.mode || '').trim().toLowerCase()
    return {
      mode: ['pet', 'card', 'panel'].includes(mode) ? mode : '',
      reducedMotion: message.args?.reducedMotion === true,
    }
  }
  if (message.command === 'get_desktop_plugin_view_mode_transition') {
    const mode = String(message.args?.mode || '').trim().toLowerCase()
    return {
      mode: ['pet', 'card', 'panel'].includes(mode) ? mode : '',
    }
  }
  if (message.command === 'set_desktop_plugin_dock') {
    const dock = String(message.args?.dock || '').trim().toLowerCase()
    return {
      dock: ['left', 'right'].includes(dock) ? dock : '',
    }
  }
  if (message.command === 'import_dropped_files' || message.command === 'discard_dropped_files') {
    return {
      dropId: String(message.args?.dropId || '').trim(),
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
    if (message.command === 'import_dropped_files') {
      if (!fileDropEnabled) throw new Error('当前桌面插件未获 fileDrop 能力')
      const args = commandArgs(message as PluginRequest)
      response.result = await invoke('read_desktop_plugin_drop', args)
      registeredDropIds.delete(String(args.dropId || ''))
    } else if (message.command === 'discard_dropped_files') {
      if (!fileDropEnabled) throw new Error('当前桌面插件未获 fileDrop 能力')
      const args = commandArgs(message as PluginRequest)
      response.result = await invoke('discard_desktop_plugin_drop', args)
      registeredDropIds.delete(String(args.dropId || ''))
    } else {
      response.result = await invoke(message.command, commandArgs(message as PluginRequest))
    }
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
  const plugin = payload.plugins?.find((candidate) => candidate.name === DESKTOP_PET_PLUGIN_NAME)
  if (!plugin?.entry_url) throw new Error('桌宠插件未启用或入口不可用')

  const entryUrl = new URL(plugin.entry_url, apiBase)
  if (entryUrl.origin !== new URL(apiBase).origin) throw new Error('桌面插件入口不属于 Core')
  pluginOrigin = entryUrl.origin
  fileDropEnabled = plugin.fileDrop === true
  document.title = plugin.title || plugin.name

  await invoke('configure_desktop_plugin_window', { spec: plugin.window || {} })
  await listenForWindowMoves()
  await new Promise<void>((resolve, reject) => {
    frame.addEventListener('load', () => resolve(), { once: true })
    frame.addEventListener('error', () => reject(new Error('桌面插件页面加载失败')), { once: true })
    frame.src = entryUrl.toString()
  })
  await listenForFileDrops()
  await invoke('show_current_window')
}

start().catch(showError)

export {}
