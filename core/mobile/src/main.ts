import { createApp } from 'vue'

const root = document.querySelector<HTMLElement>('#app')

function renderStartupError(error: unknown): void {
  if (!root) return
  const surface = document.createElement('main')
  surface.setAttribute('role', 'alert')
  surface.style.cssText = [
    'min-height:100dvh',
    'box-sizing:border-box',
    'display:grid',
    'place-content:center',
    'gap:12px',
    'padding:28px',
    'background:#111111',
    'color:#f7f7f7',
    'font:15px/1.6 system-ui,sans-serif',
  ].join(';')
  const title = document.createElement('strong')
  title.textContent = 'Sunday 启动失败'
  const detail = document.createElement('pre')
  detail.style.cssText = 'max-width:100%;white-space:pre-wrap;overflow-wrap:anywhere;color:#ffb4ab'
  detail.textContent = error instanceof Error ? (error.stack || error.message) : String(error)
  surface.append(title, detail)
  root.replaceChildren(surface)
}

window.addEventListener('error', (event) => renderStartupError(event.error || event.message))
window.addEventListener('unhandledrejection', (event) => renderStartupError(event.reason))

void import('./App.vue')
  .then(({ default: App }) => {
    if (!root) throw new Error('Missing #app mount element')
    createApp(App).mount(root)
  })
  .catch(renderStartupError)
