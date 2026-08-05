import { invoke } from '@tauri-apps/api/core';

async function init() {
  try {
    // In Tauri: ask Rust for the dynamically chosen port
    const apiBase = await invoke<string>('get_api_base');
    (window as any).__LAMTOOLS_API_BASE__ = apiBase + '/api/core';
  } catch {
    console.log('[Main] Not running in Tauri, using default API base');
  }

  // Window controls: invoke custom Rust commands
  (window as any).__LAMTOOLS_MINIMIZE = () => invoke('minimize_window');
  (window as any).__LAMTOOLS_TOGGLE_MAXIMIZE = () => invoke('toggle_maximize_window');
  (window as any).__LAMTOOLS_CLOSE = () => invoke('close_window');

  // Native directory picker: returns selected path or null (cancelled)
  ;(window as any).__LAMTOOLS_PICK_DIRECTORY = async (): Promise<string | null> => {
    return await invoke<string | null>('pick_directory')
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