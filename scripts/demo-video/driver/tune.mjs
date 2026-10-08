// Tune the capture: pick a viewport/size/quality that keeps the app smooth.
//
//   node scripts/demo-video/driver/tune.mjs
//
// CDP screencast reports CSS pixels in metadata, so this measures the real
// encoded frame size (JPEG header) to know what resolution the edit gets.

import { chromium } from 'playwright'

const PORT = process.env.DEMO_CDP_PORT || '9222'

const TICKER = `
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
`

function jpegSize(buffer) {
  let offset = 2
  while (offset < buffer.length - 9) {
    if (buffer[offset] !== 0xff) {
      offset += 1
      continue
    }
    const marker = buffer[offset + 1]
    const length = buffer.readUInt16BE(offset + 2)
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
      return { height: buffer.readUInt16BE(offset + 5), width: buffer.readUInt16BE(offset + 7) }
    }
    offset += 2 + length
  }
  return null
}

async function scenario(context, page, label, options) {
  const cdp = await context.newCDPSession(page)
  await cdp.send('Page.enable')
  if (options.viewport) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: options.viewport.width,
      height: options.viewport.height,
      deviceScaleFactor: options.viewport.scale,
      mobile: false,
    })
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  let frames = 0
  let bytes = 0
  let size = '?'
  const gaps = []
  let last = 0
  const started = Date.now()
  cdp.on('Page.screencastFrame', (frame) => {
    const now = Date.now()
    if (last) gaps.push(now - last)
    last = now
    frames += 1
    const buffer = Buffer.from(frame.data, 'base64')
    bytes += buffer.length
    if (frames === 5) {
      const parsed = jpegSize(buffer)
      size = parsed ? `${parsed.width}x${parsed.height}` : 'unknown'
    }
    cdp.send('Page.screencastFrameAck', { sessionId: frame.sessionId }).catch(() => {})
  })
  await cdp.send('Page.startScreencast', {
    format: 'jpeg',
    quality: options.quality ?? 92,
    maxWidth: options.maxWidth ?? 4096,
    maxHeight: options.maxHeight ?? 4096,
    everyNthFrame: options.everyNthFrame ?? 1,
  })
  await new Promise((resolve) => setTimeout(resolve, options.durationMs ?? 3000))
  await cdp.send('Page.stopScreencast').catch(() => {})
  const windowMs = Date.now() - started
  await cdp.detach().catch(() => {})
  const avgGap = gaps.length ? gaps.reduce((a, b) => a + b, 0) / gaps.length : 0
  const maxGap = gaps.length ? Math.max(...gaps) : 0
  console.log(
    `${label.padEnd(28)} fps=${((frames * 1000) / windowMs).toFixed(1).padStart(5)} ` +
      `frame=${size.padEnd(10)} avg=${(frames ? bytes / frames / 1024 : 0).toFixed(0).padStart(4)}KB ` +
      `gap avg=${avgGap.toFixed(0)}ms max=${maxGap.toFixed(0)}ms`,
  )
  if (options.viewport) await cdp.send('Emulation.clearDeviceMetricsOverride').catch(() => {})
  return { frames, windowMs, size }
}

async function main() {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`, { timeout: 20000 })
  const context = browser.contexts()[0]
  const page = context.pages()[0]
  await page.evaluate(TICKER)

  await scenario(context, page, 'native 974x609 (ticker)', {})
  await scenario(context, page, '1440x900 @2 every1', {
    viewport: { width: 1440, height: 900, scale: 2 },
  })
  await scenario(context, page, '1440x900 @2 every2', {
    viewport: { width: 1440, height: 900, scale: 2 },
    everyNthFrame: 2,
  })
  await scenario(context, page, '1600x900 @2 every1', {
    viewport: { width: 1600, height: 900, scale: 2 },
  })
  await scenario(context, page, '1600x900 @2 every2', {
    viewport: { width: 1600, height: 900, scale: 2 },
    everyNthFrame: 2,
  })
  await scenario(context, page, '1600x900 @1 every1', {
    viewport: { width: 1600, height: 900, scale: 1 },
  })

  await browser.close()
}

main().catch((error) => {
  console.error('tune failed:', error)
  process.exit(1)
})
