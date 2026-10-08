// Check that the window is still producing frames; reload to recover if the
// compositor stalled (a stalled frame supply silently produces a frozen take).
import { chromium } from 'playwright'
import fs from 'node:fs'

const PORT = process.env.DEMO_CDP_PORT || '9222'

export async function measureFps(context, page, durationMs = 2000) {
  const cdp = await context.newCDPSession(page)
  await cdp.send('Page.enable')
  let frames = 0
  const started = Date.now()
  cdp.on('Page.screencastFrame', (frame) => {
    frames += 1
    cdp.send('Page.screencastFrameAck', { sessionId: frame.sessionId }).catch(() => {})
  })
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 80, maxWidth: 4096, maxHeight: 4096, everyNthFrame: 1 })
  await new Promise((resolve) => setTimeout(resolve, durationMs))
  await cdp.send('Page.stopScreencast').catch(() => {})
  await cdp.detach().catch(() => {})
  return (frames * 1000) / (Date.now() - started)
}

export async function ensureAnimating(context, page, { minFps = 20, reloadOnStall = true } = {}) {
  await page.evaluate(`
    (() => {
      if (window.__demoTicker) return 'already'
      const node = document.createElement('div')
      node.setAttribute('data-demo-ticker', '1')
      node.style.cssText = 'position:fixed;left:0;top:0;width:2px;height:2px;pointer-events:none;z-index:2147483647;opacity:0.01;background:#fff;will-change:transform'
      document.documentElement.appendChild(node)
      let n = 0
      const step = () => { n = (n + 1) % 4096; node.style.transform = 'translate3d(' + n + 'px,0,0)'; window.__demoTicker = requestAnimationFrame(step) }
      window.__demoTicker = requestAnimationFrame(step)
      return 'installed'
    })()
  `)
  let fps = await measureFps(context, page, 1500)
  if (fps < minFps && reloadOnStall) {
    console.log(`  frame supply stalled (${fps.toFixed(1)} fps) -> reloading window`)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(2500)
    await page.evaluate(`
      (() => {
        const node = document.createElement('div')
        node.setAttribute('data-demo-ticker', '1')
        node.style.cssText = 'position:fixed;left:0;top:0;width:2px;height:2px;pointer-events:none;z-index:2147483647;opacity:0.01;background:#fff;will-change:transform'
        document.documentElement.appendChild(node)
        let n = 0
        const step = () => { n = (n + 1) % 4096; node.style.transform = 'translate3d(' + n + 'px,0,0)'; window.__demoTicker = requestAnimationFrame(step) }
        window.__demoTicker = requestAnimationFrame(step)
        return 'installed'
      })()
    `)
    fps = await measureFps(context, page, 1500)
  }
  return fps
}

async function main() {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`, { timeout: 20000 })
  const context = browser.contexts()[0]
  const page = context.pages()[0]
  const fps = await ensureAnimating(context, page)
  console.log(`frame supply: ${fps.toFixed(1)} fps`)
  await browser.close()
  if (fps < 10) process.exit(1)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
