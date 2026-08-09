import { convertFileSrc, invoke } from '@tauri-apps/api/core';

async function init() {
  try {
    // In Tauri: ask Rust for the dynamically chosen port
    const apiBase = await invoke<string>('get_api_base');
    (window as any).__LAMTOOLS_API_BASE__ = apiBase + '/api/core';
  } catch {
    console.log('[Main] Not running in Tauri, using default API base');
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
  const App = (await import('../../ui/src/demo/App.vue')).default;
  createApp(App).mount('#app');
}

init();