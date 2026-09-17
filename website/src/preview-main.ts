import { createApp, type App } from 'vue'
import LamToolsApp from '@ui/app/LamToolsApp.vue'
import { SUNDAY_DARK_THEME, SUNDAY_LIGHT_THEME } from '@ui/helpers/theme'
import {
  createWebsiteMockRuntime,
  type WebsiteMockRuntime,
} from './mock/runtime'
import '@ui/styles/variables.css'
import '@ui/styles/base.css'
import '@ui/styles/layout.css'

type PreviewTheme = 'ivory' | 'graphite'
interface PreviewThemeMessage {
  type: 'lamtools:preview-theme'
  theme: PreviewTheme
}

// The shared workbench scrolls its thread sentinel into view after mounting.
// Inside an iframe, the browser may also scroll the parent page until the
// iframe itself is visible. Keep thread scrolls inside the preview document so
// theme reloads never pull the landing page away from its current section.
Element.prototype.scrollIntoView = function scrollInsidePreview() {
  let container = this.parentElement
  while (container && container !== document.body) {
    const style = getComputedStyle(container)
    const scrollY = /(auto|scroll)/.test(style.overflowY) && container.scrollHeight > container.clientHeight
    const scrollX = /(auto|scroll)/.test(style.overflowX) && container.scrollWidth > container.clientWidth
    if (scrollY || scrollX) {
      const target = this.getBoundingClientRect()
      const boundary = container.getBoundingClientRect()
      if (scrollY && target.bottom > boundary.bottom) container.scrollTop += target.bottom - boundary.bottom
      if (scrollY && target.top < boundary.top) container.scrollTop -= boundary.top - target.top
      if (scrollX && target.right > boundary.right) container.scrollLeft += target.right - boundary.right
      if (scrollX && target.left < boundary.left) container.scrollLeft -= boundary.left - target.left
      return
    }
    container = container.parentElement
  }
}

document.body.classList.add('core-preview-document')

const root = document.querySelector<HTMLElement>('#app')
if (!root) throw new Error('Sunday preview root is missing')

let activeTheme: PreviewTheme | null = null
let activeRuntime: WebsiteMockRuntime | null = null
let activeApp: App<Element> | null = null

function applyDocumentTheme(theme: PreviewTheme) {
  const dark = theme === 'graphite'
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
  document.querySelector('meta[name="theme-color"]')?.setAttribute(
    'content',
    dark ? '#1b1d22' : '#f8f7f3',
  )

  // LamToolsApp owns theme selection in the shared UI. Seed its existing
  // preference shape before mounting so the real app uses the website theme.
  try {
    const key = 'lamtools.core.ui.preferences'
    const stored = JSON.parse(window.localStorage.getItem(key) || '{}') as Record<string, unknown>
    window.localStorage.setItem(key, JSON.stringify({
      ...stored,
      themeMode: dark ? 'dark' : 'light',
      theme: dark ? SUNDAY_DARK_THEME : SUNDAY_LIGHT_THEME,
      lightTheme: SUNDAY_LIGHT_THEME,
      darkTheme: SUNDAY_DARK_THEME,
    }))
  } catch {
    // Preview remains usable when storage is disabled by the browser.
  }
}

function mountPreview(theme: PreviewTheme) {
  if (theme === activeTheme && activeApp) return

  activeApp?.unmount()
  activeRuntime?.close()
  root.replaceChildren()

  applyDocumentTheme(theme)
  activeRuntime = createWebsiteMockRuntime()
  activeApp = createApp(LamToolsApp, {
    runtime: activeRuntime,
    showPreviewTitleBar: true,
  })
  activeApp.mount(root)
  activeTheme = theme
}

function isThemeMessage(value: unknown): value is PreviewThemeMessage {
  if (!value || typeof value !== 'object') return false
  const message = value as Partial<PreviewThemeMessage>
  return message.type === 'lamtools:preview-theme'
    && (message.theme === 'ivory' || message.theme === 'graphite')
}

function initialTheme(): PreviewTheme {
  try {
    const parentTheme = window.parent.document.documentElement.dataset.siteTheme
    if (parentTheme === 'ivory' || parentTheme === 'graphite') return parentTheme
  } catch {
    // Standalone/cross-origin preview falls back to its query or graphite.
  }
  return new URLSearchParams(window.location.search).get('theme') === 'ivory'
    ? 'ivory'
    : 'graphite'
}

function handleMessage(event: MessageEvent<unknown>) {
  if (event.source !== window.parent || event.origin !== window.location.origin) return
  if (isThemeMessage(event.data)) mountPreview(event.data.theme)
}

window.addEventListener('message', handleMessage)
mountPreview(initialTheme())

window.addEventListener('pagehide', () => {
  window.removeEventListener('message', handleMessage)
  activeApp?.unmount()
  activeRuntime?.close()
  activeApp = null
  activeRuntime = null
}, { once: true })
