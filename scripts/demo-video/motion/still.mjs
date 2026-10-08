// Grab stills from a scene at chosen times, for design review.
//
//   node scripts/demo-video/motion/still.mjs --scene opening --at 0.6,1.6,2.6,3.6,5.8
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const args = process.argv.slice(2)
const value = (name, fallback) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? fallback : args[index + 1]
}

const SCENE = value('scene', 'opening')
const TIMES = String(value('at', '1,3,5')).split(',').map(Number)
const WIDTH = Number(value('width', 1920))
const HEIGHT = Number(value('height', 1080))
const OUT = value('out', `E:/LamDemo/motion/${SCENE}/stills`)

fs.mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 })
await page.goto(`file://${path.join(HERE, 'scenes', `${SCENE}.html`).replace(/\\/g, '/')}`)
await page.waitForFunction(() => window.__sceneReady === true)
await page.evaluate(() => document.fonts && document.fonts.ready)
for (const time of TIMES) {
  await page.evaluate((t) => window.renderFrame(t), time)
  const file = path.join(OUT, `${String(time).replace('.', '_')}s.png`)
  await page.screenshot({ path: file, animations: 'disabled' })
  console.log(`  ${file}`)
}
await browser.close()
