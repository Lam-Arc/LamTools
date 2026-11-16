// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('capture editor gallery', () => {
  it('loads the real embedded editor, supports selection, and exposes its source', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CaptureEditor')
      await page.locator('[data-load-capture]').click()
      const capture = page.locator('.preview .capture--sandbox')
      await capture.waitFor()
      const canvas = capture.locator('canvas')
      const box = await canvas.boundingBox()
      await page.mouse.move(box!.x + 30, box!.y + 30)
      await page.mouse.down()
      await page.mouse.move(box!.x + 100, box!.y + 100)
      await page.mouse.up()
      expect(await capture.locator('.capture__hint').count()).toBe(0)
      await capture.getByRole('button', { name: '发送', exact: true }).click()
      expect(await page.locator('[data-capture-result]').innerText()).toContain('本地示例')
      await page.locator('[data-source="CaptureEditor"]').click()
      expect(await page.locator('[data-source-content="CaptureEditor"]').textContent()).toContain('capture--sandbox')
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
