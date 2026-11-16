// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('reduced motion for existing UI', () => {
  it('stops remote status, plugin status and Ping ring motion when requested', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1000, height: 800 } })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/motion.ts' })
      for (const selector of ['.core-remote-badge.is-lost', '.plugin-status-row.is-pending .plugin-status-dot', '.ping-ring__svg', '.ping-ring__tier']) {
        const element = page.locator('#motion-fixture').locator(selector)
        expect(await element.evaluate(el => getComputedStyle(el).animationName)).not.toBe('none')
        await page.emulateMedia({ reducedMotion: 'reduce' })
        expect(await element.evaluate(el => getComputedStyle(el).animationName)).toBe('none')
        await page.emulateMedia({ reducedMotion: 'no-preference' })
      }
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
