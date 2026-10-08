// Measure the live Sunday window: geometry + achievable screencast frame rate.
//
//   node scripts/demo-video/driver/probe.mjs
//
// Notes for whoever reads this next:
//  * CDP screencast only emits a frame when the compositor produces one, so an
//    idle window yields ~0 fps.  The demo injects a 1px rAF "ticker" while
//    capturing to guarantee a steady frame supply; this probe measures both.
//  * devicePixelRatio decides how much real detail a camera push-in can keep.

import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const PORT = process.env.DEMO_CDP_PORT || '9222'
const OUT = process.env.DEMO_OUT || 'E:/LamDemo/probe'

const TICKER = `
(() => {
  if (window.__demoTicker) return 'already'
  const node = document.createElement('div')
  node.setAttribute('data-demo-ticker', '1')
  node.style.cssText = 'position:fixed;left:0;top:0;width:2px;height:2px;pointer-events:none;z-index:2147483647;opacity:0.01;background:#fff;will-change:transform';
  document.documentElement.appendChild(node)
  let n = 0
  const step = () => {
    n = (n + 1) % 4096
    node.style.transform = 'translate3d(' + n + 'px,0,0)'
    window.__demoTicker = requestAnimationFrame(step)
  }
  window.__demoTicker = requestAnimationFrame(step)
  return 'installed'
})()
`

const TICKER_OFF = `
(() => {
  if (window.__demoTicker) { cancelAnimationFrame(window.__demoTicker); window.__demoTicker = null }
  const node = document.querySelector('[data-demo-ticker]')
  if (node) node.remove()
  return 'removed'
})()
`

async function main() {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`, { timeout: 20000 })
  const context = browser.contexts()[0]
  const page = context.pages()[0]
  console.log('page:', page.url())

  const info = await page.evaluate(() => ({
    dpr: window.devicePixelRatio,
    inner: [window.innerWidth, window.innerHeight],
    outer: [window.outerWidth, window.outerHeight],
    screen: [screen.width, screen.height],
    avail: [screen.availWidth, screen.availHeight],
  }))
  console.log('geometry:', JSON.stringify(info))
  await page.screenshot({ path: path.join(OUT, 'window.png') })

  console.log('screencast idle  :', JSON.stringify(await measure(context, page, 2500)))
  console.log('ticker           :', await page.evaluate(TICKER))
  console.log('screencast ticker:', JSON.stringify(await measure(context, page, 3000)))
  console.log('ticker off       :', await page.evaluate(TICKER_OFF))

  await browser.close()
}

async function measure(context, page, durationMs) {
  const cdp = await context.newCDPSession(page)
  await cdp.send('Page.enable')
  let frames = 0
  let bytes = 0
  let size = { width: 0, height: 0 }
  const started = Date.now()
  cdp.on('Page.screencastFrame', (frame) => {
    frames += 1
    bytes += Buffer.from(frame.data, 'base64').length
    size = {
      width: Math.round(frame.metadata.deviceWidth || size.width),
      height: Math.round(frame.metadata.deviceHeight || size.height),
    }
    cdp.send('Page.screencastFrameAck', { sessionId: frame.sessionId }).catch(() => {})
  })
  await cdp.send('Page.startScreencast', {
    format: 'jpeg',
    quality: 92,
    maxWidth: 4096,
    maxHeight: 4096,
    everyNthFrame: 1,
  })
  await new Promise((resolve) => setTimeout(resolve, durationMs))
  await cdp.send('Page.stopScreencast').catch(() => {})
  const windowMs = Date.now() - started
  await cdp.detach().catch(() => {})
  return {
    fps: Number(((frames * 1000) / windowMs).toFixed(1)),
    frames,
    size: `${size.width}x${size.height}`,
    kb: frames ? Math.round(bytes / frames / 1024) : 0,
  }
}

main().catch((error) => {
  console.error('probe failed:', error)
  process.exit(1)
})
