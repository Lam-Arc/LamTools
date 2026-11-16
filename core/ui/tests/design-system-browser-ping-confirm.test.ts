// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('Ping card confirmation layout', () => {
  it('keeps confirmation controls usable in a standalone card window', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 320, height: 500 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/ping-confirm.ts' })
      const dialog = page.getByRole('dialog', { name: '撤回此消息及后续对话？' })
      const bounds = await dialog.boundingBox()
      expect(bounds!.x).toBeGreaterThanOrEqual(0)
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(320)
      await dialog.getByRole('button', { name: '确认' }).click()
      expect(await page.locator('#ping-confirm-result').innerText()).toBe('已确认')
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
