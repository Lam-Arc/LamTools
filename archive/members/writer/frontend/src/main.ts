import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@lamtools/ui'
import '@lamtools/ui/styles.css'

async function bootstrapDesktopBridge() {
  if (!('__TAURI_INTERNALS__' in window)) {
    return
  }

  const { invoke } = await import('@tauri-apps/api/core')
  const apiBase = await invoke<string>('get_api_base')
  window.lamwriterDesktop = {
    apiBase,
    selectDirectory: async () => {
      const selected = await invoke<string | null>('select_directory')
      return selected || ''
    },
  }
}

async function main() {
  await bootstrapDesktopBridge()

  const [{ default: App }, { default: router }] = await Promise.all([
    import('./App.vue'),
    import('./router'),
  ])

  const app = createApp(App)
  app.use(createPinia())
  app.use(router)
  app.mount('#app')
}

main().catch((error) => {
  console.error('LamWriter failed to start', error)
})
