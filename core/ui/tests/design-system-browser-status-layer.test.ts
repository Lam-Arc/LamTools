// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('status layer', () => {
  it('keeps the independent overlay stop control clickable', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0, strictPort: false } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 850 }, reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/status.ts' })
      const motion = await page.locator('.cu-capsule').evaluate(element => getComputedStyle(element).animationName)
      expect(motion).toBe('none')
      const button = page.locator('.cu-bar button').first()
      await button.waitFor({ state: 'visible' })
      const hit = await button.evaluate(element => {
        const rect = element.getBoundingClientRect()
        return document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)?.closest('button') === element
      })
      expect(hit).toBe(true)
      await button.click()
      expect(await page.locator('#status-result').innerText()).toBe('已请求结束')
      await page.close()
    } finally {
      await browser.close()
      await server.close()
    }
  }, 90000)
})
