/* The product host: the real application, mounted in a document of its own.
 *
 * It is loaded in an iframe by the stage shell, which is what lets the film
 * put the product in a box: the application lays itself out for the size it
 * has been given, exactly as it would in a window of that size.
 *
 *   /app.html?scene=<name>
 *
 * `window.renderFrame(t)` sets the application to time t and resolves once it
 * has painted. New state arrives the way it really does in production — as a
 * `thread/snapshot` notification on the transport, stamped with an
 * ever-increasing revision (a snapshot that regresses is dropped on the floor).
 */

import { createApp, nextTick, type App } from 'vue'
import LamToolsApp from '@ui/app/LamToolsApp.vue'
import { SUNDAY_DARK_THEME, SUNDAY_LIGHT_THEME } from '@ui/helpers/theme'
import '@ui/styles/variables.css'
import '@ui/styles/base.css'
import '@ui/styles/layout.css'

import { createStageBackend } from './runtime'
import type { StageScene } from './timeline'

type SceneModule = { default: StageScene }

const params = new URLSearchParams(window.location.search)
const SCENE_ID = params.get('scene') || 'first-look'
/** the film's theme is a film-level decision, so it can be forced from outside */
const THEME_OVERRIDE = params.get('theme') === 'light'
  ? 'light' as const
  : params.get('theme') === 'dark' ? 'dark' as const : null

/* ------------------------------------------------------------ determinism ---- */

// A smooth scroll is wall-clock motion that CSS cannot switch off, and the
// product scrolls its thread to the newest message. Land every scroll at once.
const nativeScrollIntoView = Element.prototype.scrollIntoView
Element.prototype.scrollIntoView = function instantScrollIntoView(
  arg?: boolean | ScrollIntoViewOptions,
) {
  const options = typeof arg === 'object' && arg !== null ? { ...arg } : {}
  nativeScrollIntoView.call(this, { ...options, behavior: 'instant' as ScrollBehavior })
}

/* --------------------------------------------------------------- the app ---- */

const backend = createStageBackend()
let app: App<Element> | null = null
let scene: StageScene | null = null
let revision = 0
let knownSessions = new Set<string>()

function applyTheme(theme: 'light' | 'dark') {
  const dark = theme !== 'light'
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
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
    // storage disabled: the application keeps its own default theme
  }
}

function composerTextarea(): HTMLTextAreaElement | null {
  const byCard = document.querySelector('.composer-main-card textarea')
  if (byCard) return byCard as HTMLTextAreaElement
  const byLabel = document.querySelector('textarea[aria-label]')
  if (byLabel) return byLabel as HTMLTextAreaElement
  const all = Array.from(document.querySelectorAll('textarea')) as HTMLTextAreaElement[]
  return all.length ? all[all.length - 1] : null
}

/** Types into the real composer: Vue's `@input` binding does the rest. */
function setComposerDraft(text: string) {
  const el = composerTextarea()
  if (!el) return
  if (el.value === text) return
  el.value = text
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

async function settle(frames = 2) {
  await nextTick()
  for (let index = 0; index < frames; index += 1) {
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  }
}

/* ------------------------------------------------------------------ boot ---- */

async function boot() {
  const module = (await import(/* @vite-ignore */ `../scenes/${SCENE_ID}.ts`)) as SceneModule
  scene = module.default

  // the first frame's state has to exist before the application asks for it
  const opening = scene.data(0, 1)
  backend.state.projects = opening.projects as Record<string, unknown>[]
  backend.state.sessions = opening.sessions as Record<string, unknown>[]
  backend.state.models = [{
    id: 'demo-model',
    provider_id: 'demo-provider',
    model_id: 'demo-model',
    display_name: 'Sunday Demo',
    context_window: 1_048_576,
    max_output_tokens: 16_384,
    thinking_supported: true,
    thinking_budget: 8_192,
    reasoning_off_supported: true,
    temperature: 0.2,
  }]
  backend.state.providers = [{
    id: 'demo-provider',
    name: 'Demo provider',
    api_type: 'openai_compatible',
    base_url: '',
    has_api_key: false,
  }]
  backend.state.defaultModelId = 'demo-model'
  backend.state.snapshot = opening.snapshot
  knownSessions = new Set((opening.sessions as { id: string }[]).map((session) => session.id))

  applyTheme(THEME_OVERRIDE || opening.theme || 'dark')

  app = createApp(LamToolsApp, { runtime: backend.runtime, showPreviewTitleBar: false })
  app.mount(document.getElementById('app') as HTMLElement)

  const deadline = Date.now() + 30_000
  while (!composerTextarea() && Date.now() < deadline) {
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  }
  await settle(3)
}

/* ----------------------------------------------------------- the timeline ---- */

async function renderFrame(t: number) {
  if (!scene) return
  const data = scene.data(t, ++revision)

  const theme = THEME_OVERRIDE || data.theme
  if (theme) applyTheme(theme)
  backend.state.projects = data.projects as Record<string, unknown>[]
  backend.state.sessions = data.sessions as Record<string, unknown>[]
  for (const session of data.sessions as { id: string }[]) {
    if (!knownSessions.has(session.id)) {
      knownSessions.add(session.id)
      backend.push('session/created', { session })
    }
  }

  const snapshot = data.snapshot as { thread_id?: string }
  backend.state.snapshot = snapshot
  backend.pushSnapshot(snapshot)

  if (typeof data.composerDraft === 'string') setComposerDraft(data.composerDraft)

  await settle(2)
}

window.stage = {
  renderFrame,
  size: () => ({ width: window.innerWidth, height: window.innerHeight }),
}

boot()
  .then(() => renderFrame(0))
  .then(() => { ;(window as unknown as { __appReady?: boolean }).__appReady = true })
  .catch((error) => {
    console.error('stage product host failed to boot', error)
    ;(window as unknown as { __appError?: string }).__appError = String(error)
  })
