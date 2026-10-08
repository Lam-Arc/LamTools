// Dump every element carrying a data-* attribute: one shot, exact selectors.
import { chromium } from 'playwright'

const browser = await chromium.connectOverCDP(`http://127.0.0.1:${process.env.DEMO_CDP_PORT || '9222'}`, { timeout: 30000 })
const context = browser.contexts()[0]
const page = context.pages()[0]
const cdp = await context.newCDPSession(page)
await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1.28, mobile: false })
await page.waitForTimeout(800)

const dump = async (label) => {
  const rows = await page.evaluate(() => {
    const out = []
    document.querySelectorAll('*').forEach((node) => {
      const attrs = Array.from(node.attributes || []).filter((a) => a.name.startsWith('data-'))
      if (!attrs.length) return
      const rect = node.getBoundingClientRect()
      const visible = rect.width > 0 && rect.height > 0
      if (!visible) return
      out.push(
        attrs.map((a) => `${a.name}="${a.value}"`).join(' ') +
          ` <${node.tagName.toLowerCase()}> "${(node.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 34)}"`,
      )
    })
    return out
  })
  console.log(`\n### ${label} (${rows.length})`)
  console.log(rows.slice(0, 90).join('\n'))
}

await dump('workspace')
const rail = page.locator('[data-rail-entry="settings"]')
if (await rail.count()) {
  await rail.first().click()
  await page.waitForTimeout(1200)
  await dump('settings-rail')
const view = page.locator('[data-model-catalog-view="provider"]')
if (await view.count()) { await view.first().click(); await page.waitForTimeout(900); await dump('settings-provider-view') }
}
await browser.close()
