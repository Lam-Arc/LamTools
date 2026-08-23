import { convertFileSrc, invoke } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';

async function init() {
  const isTauri = Boolean((window as any).__TAURI_INTERNALS__)
  const windowParams = new URLSearchParams(window.location.search)
  if (isTauri) {
    // The Pet windows are created in parallel with WebView2. Do not mount a
    // Pet surface against Vite's fallback URL while the Core port is still
    // starting; that race presents as an endless "connecting" overlay.
    let apiBase = windowParams.get('api_base') || ''
    let lastError: unknown
    for (let attempt = 0; attempt < 120 && !apiBase; attempt += 1) {
      try {
        apiBase = await invoke<string>('get_api_base')
      } catch (error) {
        lastError = error
        await new Promise(resolve => setTimeout(resolve, 250))
      }
    }
    if (!apiBase) throw lastError instanceof Error ? lastError : new Error('LamTools Core did not become ready')
    ;(window as any).__LAMTOOLS_API_BASE__ = apiBase + '/api/core'
  } else {
    console.log('[Main] Not running in Tauri, using default API base')
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

  // Diagnostic: verify custom commands are registered
  try {
    const pong = await invoke<string>('ping');
    console.log('[Main] ping:', pong);
  } catch (e) {
    console.error('[Main] ping failed:', e);
  }

  const { createApp } = await import('vue');
  let label = windowParams.get('window') || getCurrentWindow().label;
  try {
    label = await invoke<string>('get_window_label');
  } catch {
    // Browser fallback uses the query/current-window label above.
  }
  const App = label === 'pet'
    ? (await import('../../ui/src/pet/PetApp.vue')).default
    : label === 'pet-overlay'
      ? (await import('../../ui/src/pet/PetOverlayApp.vue')).default
      : (await import('../../ui/src/demo/App.vue')).default;
  createApp(App).mount('#app');
}

init();
