import { convertFileSrc, invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event'
import { createApp } from 'vue'
import { createDirectTransport } from '../../ui/src/transport'
import { createLamToolsRuntime } from '../../ui/src/app/runtime'
import LamToolsApp from '../../ui/src/app/LamToolsApp.vue'
import {
  completeStartupSplash,
  startStartupSplash,
} from '../../ui/src/motion/startupSplash'

// The desktop shell owns every right-click interaction. Prevent WebView's
// native browser menu globally without stopping propagation, so scoped custom
// menus (workflow canvas, sidebar, etc.) still receive the event.
document.addEventListener('contextmenu', (event) => event.preventDefault(), { capture: true })

startStartupSplash()

const BACKEND_API_RETRY_ATTEMPTS = 80
const BACKEND_API_RETRY_DELAY_MS = 250

function isTauriRuntime(): boolean {
  return typeof (window as any).__TAURI_INTERNALS__ === 'object'
}

async function resolveBackendApiBase(): Promise<string | null> {
  if (!isTauriRuntime()) return null

  let lastError: unknown
  for (let attempt = 0; attempt < BACKEND_API_RETRY_ATTEMPTS; attempt++) {
    try {
      const apiBase = await invoke<string>('get_api_base')
      if (/^http:\/\/127\.0\.0\.1:\d+$/.test(apiBase)) return apiBase
      throw new Error(`invalid backend API base: ${apiBase}`)
    } catch (error) {
      lastError = error
      if (attempt + 1 < BACKEND_API_RETRY_ATTEMPTS) {
        await new Promise((resolve) => setTimeout(resolve, BACKEND_API_RETRY_DELAY_MS))
      }
    }
  }

  throw new Error(`Sunday backend API unavailable: ${String(lastError)}`)
}

async function init() {
  const apiBase = await resolveBackendApiBase()
  if (apiBase) {
    // In Tauri, wait for Rust to publish the dynamically chosen backend port
    // before constructing the direct transport. Packaged windows never rely
    // on a relative Core URL.
  } else {
    console.log('[Main] Not running in Tauri, using default API base');
  }

  // Packaged app version (from tauri.conf.json). The settings "关于与更新"
  // section reads this instead of hardcoding a string; it stays undefined in
  // plain-browser dev so the UI falls back to its own placeholder.
  try {
    const info = await invoke<{ name: string; version: string }>('get_app_info');
    (window as any).__LAMTOOLS_APP_VERSION__ = info.version;
  } catch {
    console.log('[Main] get_app_info unavailable, version stays undefined');
  }

  // Local file URL resolver (asset protocol): artifact previews read files
  // straight from disk (.lam/artifacts/...) instead of round-tripping HTTP.
  // Falls back to undefined in plain browsers (dev via vite).
  (window as any).__LAMTOOLS_FILE_SRC__ = (absolutePath: string): string => {
    try {
      return convertFileSrc(absolutePath);
    } catch (e) {
      console.error('[Main] convertFileSrc failed:', e);
      return '';
    }
  };

  // Window controls: invoke custom Rust commands
  (window as any).__LAMTOOLS_MINIMIZE = () => invoke('minimize_window');
  (window as any).__LAMTOOLS_TOGGLE_MAXIMIZE = () => invoke('toggle_maximize_window');
  (window as any).__LAMTOOLS_CLOSE = () => invoke('close_window');

  await Promise.all([
    listen<boolean>('lamtools://window/maximize-hover', ({ payload }) => {
      window.dispatchEvent(new CustomEvent('lamtools:maximize-hover', { detail: payload }))
    }),
    listen<boolean>('lamtools://window/maximize-press', ({ payload }) => {
      window.dispatchEvent(new CustomEvent('lamtools:maximize-press', { detail: payload }))
    }),
    listen('lamtools://window/maximize-click', () => invoke('toggle_maximize_window')),
  ])

  // Native directory picker: returns selected path or null (cancelled)
  ;(window as any).__LAMTOOLS_PICK_DIRECTORY = async (): Promise<string | null> => {
    return await invoke<string | null>('pick_directory')
  }

  // Open an external URL in the OS default browser. Returns true on success.
  // Frontend link click handlers call this instead of letting the webview
  // navigate, which would turn the app window into a browser.
  ;(window as any).__LAMTOOLS_OPEN_URL__ = async (url: string): Promise<boolean> => {
    try {
      await invoke('open_external_url', { url })
      return true
    } catch (e) {
      console.error('[Main] open_external_url failed:', e)
      return false
    }
  }

  ;(window as any).__LAMTOOLS_SHOW_DESKTOP_PLUGIN__ = async (pluginId: string): Promise<void> => {
    await invoke('show_desktop_plugin_window', { pluginId })
  }

  ;(window as any).__LAMTOOLS_REFRESH_DESKTOP_PLUGINS__ = async (): Promise<void> => {
    await invoke('reload_desktop_plugin_window')
  }

  // Mobile Control bridge.  Core UI keeps these callbacks optional so the
  // same settings component can render in the website/browser showcase.
  ;(window as any).__LAMTOOLS_REMOTE_STATUS__ = async (): Promise<unknown> => {
    return await invoke('remote_gateway_status')
  }
  ;(window as any).__LAMTOOLS_REMOTE_START__ = async (): Promise<unknown> => {
    return await invoke('remote_gateway_start')
  }
  ;(window as any).__LAMTOOLS_REMOTE_STOP__ = async (): Promise<unknown> => {
    return await invoke('remote_gateway_stop')
  }
  ;(window as any).__LAMTOOLS_REMOTE_PAIRING_CREATE__ = async (): Promise<unknown> => {
    return await invoke('remote_pairing_create')
  }
  ;(window as any).__LAMTOOLS_REMOTE_REVOKE__ = async (deviceId: string): Promise<boolean> => {
    return await invoke<boolean>('remote_device_revoke', { deviceId })
  }
  ;(window as any).__LAMTOOLS_REMOTE_ACCOUNT_STATUS__ = async (): Promise<unknown> => {
    return await invoke('remote_account_status')
  }
  ;(window as any).__LAMTOOLS_REMOTE_ACCOUNT_IDENTITY__ = async (scope?: { serverId: string; username: string }): Promise<unknown> => {
    return await invoke('remote_account_identity', scope || {})
  }
  ;(window as any).__LAMTOOLS_REMOTE_ACCOUNT_SAVE__ = async (session: unknown): Promise<unknown> => {
    return await invoke('remote_account_save', { session })
  }
  ;(window as any).__LAMTOOLS_REMOTE_ACCOUNT_LOGOUT__ = async (): Promise<void> => {
    await invoke('remote_account_logout')
  }

  // Diagnostic: verify custom commands are registered
  try {
    const pong = await invoke<string>('ping');
    console.log('[Main] ping:', pong);
  } catch (e) {
    console.error('[Main] ping failed:', e);
  }

  if (!apiBase) throw new Error('Sunday backend API unavailable')
  const transport = createDirectTransport({ apiBase: `${apiBase}/api/core` })
  const runtime = createLamToolsRuntime({
    transport,
    platform: 'desktop',
    capabilities: {
      filePicker: true,
      notifications: true,
      desktopWindow: true,
    },
  })
  createApp(LamToolsApp, { runtime }).mount('#app')
  completeStartupSplash()
}

init();
