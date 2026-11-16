// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('Ping ring gallery', () => {
  it('renders the actual ring, compares the tier and exposes source', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('PingRing')
      const ring = page.locator('.preview .ping-ring__svg')
      await ring.waitFor()
      expect(await ring.locator('.ping-ring__tier').count()).toBe(1)
      expect(await ring.evaluate(el => getComputedStyle(el).animationName)).toBe('none')
      await page.getByLabel('显示子环').uncheck()
      expect(await ring.locator('.ping-ring__tier').count()).toBe(0)
      await page.locator('[data-source="PingRing"]').click()
      expect(await page.locator('[data-source-content="PingRing"]').textContent()).toContain('prefers-reduced-motion')
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
