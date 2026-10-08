/* The stage shell: the picture around the product.
 *
 *   /?scene=<name>&captions=0
 *
 * It owns the ambient background, the box the product sits in, and the
 * cosmetics drawn over it (the cursor, a click ripple, review captions). The
 * product itself lives in an iframe — its root lays itself out for whatever
 * size that box is, so widening or narrowing the box is a real layout change
 * inside the application rather than a scaled picture.
 *
 * `window.renderFrame(t)` sets the whole stage to time t and resolves once it
 * has painted, so a driver can walk the timeline frame by frame.
 */

import type { StageScene } from './timeline'

type SceneModule = { default: StageScene }
type ProductWindow = Window & {
  stage?: { renderFrame: (t: number) => Promise<void> }
  __appReady?: boolean
  __appError?: string
}

const params = new URLSearchParams(window.location.search)
const SCENE_ID = params.get('scene') || 'first-look'
const SHOW_CAPTIONS = params.get('captions') !== '0'
const THEME = params.get('theme') || ''

const frame = document.getElementById('frame') as HTMLIFrameElement
const overlay = document.getElementById('overlay') as HTMLElement
const caption = document.getElementById('caption') as HTMLElement
const capTitle = document.getElementById('capTitle') as HTMLElement
const capHint = document.getElementById('capHint') as HTMLElement
const hud = document.getElementById('hud') as HTMLElement

let scene: StageScene | null = null

function productWindow(): ProductWindow | null {
  return (frame.contentWindow as ProductWindow | null) || null
}

function applyRect(rect: { x: number; y: number; w: number; h: number; radius?: number }) {
  const style = frame.style
  style.left = `${rect.x}px`
  style.top = `${rect.y}px`
  style.width = `${rect.w}px`
  style.height = `${rect.h}px`
  style.borderRadius = `${rect.radius ?? 0}px`
}

async function settle(frames = 2) {
  for (let index = 0; index < frames; index += 1) {
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  }
}

async function renderFrame(t: number) {
  if (!scene) return
  const stage = scene.frame(t)

  applyRect(stage.rect)
  overlay.innerHTML = stage.overlay || ''

  const inner = productWindow()
  if (!inner?.stage) throw new Error('product host is gone')
  await inner.stage.renderFrame(t)

  if (SHOW_CAPTIONS) {
    caption.classList.add('on')
    hud.classList.add('on')
    capTitle.textContent = stage.caption?.title || ''
    capHint.textContent = stage.caption?.hint || ''
    hud.textContent = `${t.toFixed(1)}s / ${scene.duration.toFixed(1)}s`
  } else {
    caption.classList.remove('on')
    hud.classList.remove('on')
  }

  await settle(2)
}

async function boot() {
  const module = (await import(/* @vite-ignore */ `../scenes/${SCENE_ID}.ts`)) as SceneModule
  scene = module.default

  await new Promise<void>((resolve) => {
    frame.addEventListener('load', () => resolve(), { once: true })
    frame.src = `/app.html?scene=${encodeURIComponent(SCENE_ID)}${THEME ? `&theme=${THEME}` : ''}`
  })

  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    const inner = productWindow()
    if (inner?.__appError) throw new Error(`product host reported: ${inner.__appError}`)
    if (inner?.__appReady) break
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  if (!productWindow()?.__appReady) throw new Error('product host never became ready')

  await renderFrame(0)
}

window.sceneMeta = { duration: 0, width: window.innerWidth, height: window.innerHeight }
;(window as unknown as { renderFrame: (t: number) => Promise<void> }).renderFrame = renderFrame

boot()
  .then(() => {
    window.sceneMeta = {
      duration: (scene as StageScene).duration,
      width: window.innerWidth,
      height: window.innerHeight,
    }
    ;(window as unknown as { __sceneReady?: boolean }).__sceneReady = true
  })
  .catch((error) => {
    console.error('stage shell failed to boot', error)
    ;(window as unknown as { __sceneError?: string }).__sceneError = String(error)
  })
