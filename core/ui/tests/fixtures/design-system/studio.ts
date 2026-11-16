import { createApp } from 'vue'
import ThemeStudio from '../../../src/components/ThemeStudio.vue'

export function mountStudio() {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp(ThemeStudio)
  app.mount(host)
  return () => { app.unmount(); host.remove() }
}
mountStudio()
