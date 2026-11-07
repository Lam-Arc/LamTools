// 模型目录视觉回归：整页截图 + 窄屏/压力场景，顺带收集控制台错误与溢出信息
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const out = '.lam/artifacts/model-lab'
mkdirSync(out, { recursive: true })

const cases = [
  { name: 'dark-1440', url: '', width: 1440, height: 900 },
  { name: 'light-1440', url: '?theme=light', width: 1440, height: 900 },
  { name: 'group-dark-1440', url: '?view=group', width: 1440, height: 900 },
  { name: 'stress-dark-1440', url: '?providers=12&models=48', width: 1440, height: 900 },
  { name: 'narrow-dark-1100', url: '', width: 1100, height: 900 },
  { name: 'narrow-dark-900', url: '', width: 900, height: 900 },
]

const browser = await chromium.launch()
const report = []

for (const item of cases) {
  const page = await browser.newPage({ viewport: { width: item.width, height: item.height } })
  const errors = []
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', err => errors.push(String(err)))
  await page.goto(`http://127.0.0.1:5201/model-lab.html${item.url}`, { waitUntil: 'networkidle' })
  await page.waitForSelector('[data-model-catalog]', { timeout: 15000 })
  await page.waitForTimeout(500)

  const overflow = await page.evaluate(() => {
    const wall = document.querySelector('.mc-wall')
    const catalog = document.querySelector('[data-model-catalog]')
    const rail = document.querySelector('.mc-provider-rail')
    const rows = {}
    if (rail) {
      const tops = new Set([...rail.children].map(el => Math.round(el.getBoundingClientRect().top)))
      rows.railRows = tops.size
    }
    const tiles = [...document.querySelectorAll('.mc-tiles')]
    rows.tileRows = Math.max(0, ...tiles.map(row => new Set([...row.children].map(el => Math.round(el.getBoundingClientRect().top))).size))
    return {
      ...rows,
      pageScrollX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      wallScrollX: wall ? wall.scrollWidth > wall.clientWidth + 1 : null,
      catalogClass: catalog.className,
    }
  })

  await page.screenshot({ path: `${out}/${item.name}.png`, fullPage: false })
  report.push({ name: item.name, ...overflow, errors })
  await page.close()
}

// 卡片开关的交互核对：点开关只切启停，不打开检查器。
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
await page.goto('http://127.0.0.1:5201/model-lab.html', { waitUntil: 'networkidle' })
await page.waitForSelector('[data-model-tile]')
const before = await page.locator('[data-model-card="opencode-go-glm-5.3-flash"]').getAttribute('class')
await page.locator('[data-model-tile-toggle="opencode-go-glm-5.3-flash"] input').click()
await page.waitForTimeout(300)
const after = await page.locator('[data-model-card="opencode-go-glm-5.3-flash"]').getAttribute('class')
const inspectorOpen = await page.locator('.mc-inspector').count()
report.push({ interaction: true, before, after, inspectorOpen })

await browser.close()
console.log(JSON.stringify(report, null, 2))
