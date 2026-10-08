// Look at the window at demo viewport settings and save a still.
//
//   node scripts/demo-video/driver/look.mjs [outName] [--width 1440] [--height 900] [--scale 2]
//
// Used to inspect UI state while building beats; the same viewport settings are
// what the capture uses, so what you see here is what the video gets.
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const args = process.argv.slice(2)
const outName = args.find((item) => !item.startsWith('--')) || 'look'
const flag = (name, fallback) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? fallback : Number(args[index + 1])
}
const WIDTH = flag('width', 0)
const HEIGHT = flag('height', 0)
const SCALE = flag('scale', 0)
const OUT = process.env.DEMO_OUT || 'E:/LamDemo/probe'

const browser = await chromium.connectOverCDP(`http://127.0.0.1:${process.env.DEMO_CDP_PORT || '9222'}`, { timeout: 20000 })
const context = browser.contexts()[0]
const page = context.pages()[0]
// The window itself carries the demo viewport (see env/window.ps1); emulating
// one desynchronises input coordinates, so only do it when explicitly asked.
if (WIDTH && HEIGHT) {
  const cdp = await context.newCDPSession(page)
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: WIDTH,
    height: HEIGHT,
    deviceScaleFactor: SCALE || 1,
    mobile: false,
  })
  await page.waitForTimeout(900)
}
fs.mkdirSync(OUT, { recursive: true })
const target = path.join(OUT, `${outName}.png`)
await page.screenshot({ path: target })
const text = await page.evaluate(() => document.body.innerText.slice(0, 1200))
console.log(`saved ${target}`)
console.log('--- visible text ---')
console.log(text)
await browser.close()
