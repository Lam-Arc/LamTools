// 便于人工核对：把 EasyNet 每个页面在宽/窄两种视口下截图，并量导航是否被裁切。
// 用法：node scripts/easynet-shot.mjs [baseUrl] [outDir]
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const base = process.argv[2] || 'http://127.0.0.1:5179/easynet-preview.html'
const outDir = process.argv[3] || '../.lam/artifacts/easynet'
// 预览页用 ?page= 同时支持四个主视图与设置分区别名（proxy/network/... 会落到设置页对应分区）。
const pages = ['overview', 'transfer', 'devices', 'diagnose', 'acceleration', 'proxy', 'network', 'connections', 'security', 'advanced']
const settingsPages = new Set(['acceleration', 'proxy', 'network', 'connections', 'security', 'advanced'])
const viewports = [
  { name: 'wide', width: 890, height: 960 },
  { name: 'narrow', width: 539, height: 996 },
]

mkdirSync(outDir, { recursive: true })
const browser = await chromium.launch()
const findings = []

for (const vp of viewports) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1 })
  const page = await ctx.newPage()
  const errors = []
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', (err) => errors.push(String(err)))

  for (const name of pages) {
    const targets = [name]
    for (const target of targets) {
      const label = settingsPages.has(target) ? `settings-${target}` : target
      const url = `${base}?page=${target}`
      await page.goto(url, { waitUntil: 'networkidle' })
      await page.waitForTimeout(180)
      await page.screenshot({ path: `${outDir}/${vp.name}-${label}.png`, fullPage: false })

      const probe = await page.evaluate(() => {
        const nav = document.querySelector('.nx2-rail nav')
        const rail = document.querySelector('.nx2-rail')
        const tabs = document.querySelector('.nx2-settings-tabs')
        const box = (el) => (el ? el.getBoundingClientRect() : null)
        const items = [...document.querySelectorAll('.nx2-rail-item')].map((el) => {
          const r = el.getBoundingClientRect()
          return { text: el.textContent.trim(), left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width) }
        })
        const overflowX = Math.max(0, document.documentElement.scrollWidth - window.innerWidth)
        return {
          viewport: window.innerWidth,
          railHeight: Math.round(box(rail)?.height || 0),
          nav: nav ? { clientWidth: nav.clientWidth, scrollWidth: nav.scrollWidth } : null,
          tabsHeight: Math.round(box(tabs)?.height || 0),
          items,
          overflowX,
        }
      })
      const clipped = probe.nav ? probe.nav.scrollWidth > probe.nav.clientWidth + 1 : false
      findings.push({ size: vp.name, page: label, clipped, ...probe })
      if (clipped || probe.overflowX > 0) {
        console.log(`[裁切] ${vp.name} ${label}: nav ${probe.nav?.clientWidth}/${probe.nav?.scrollWidth}, 页面横向溢出 ${probe.overflowX}`)
      }
    }
  }
  if (errors.length) console.log(`[控制台错误] ${vp.name}: ${errors.slice(0, 4).join(' | ')}`)
  await ctx.close()
}

const tabs = findings.filter((f) => f.page.startsWith('settings'))
for (const vpName of ['wide', 'narrow']) {
  const rows = tabs.filter((f) => f.size === vpName)
  console.log(`${vpName} 设置分区栏高度: ${rows.map((r) => `${r.page.replace('settings-', '')}=${r.tabsHeight}px`).join(' ')}`)
}
console.log('导航项:', JSON.stringify(findings.find((f) => f.size === 'narrow' && f.page === 'overview')?.items))
await browser.close()
