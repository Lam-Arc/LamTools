// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('library dialog backdrop interaction', () => {
  it('does not dismiss a name or confirmation dialog when a drag starts inside', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1100, height: 800 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      for (const [name, open] of [['LibraryNameDialog', '[data-library-name-open]'], ['LibraryConfirmDialog', '[data-library-confirm-open]']]) {
        await page.getByLabel('搜索组件').fill(name)
        await page.locator(open).click()
        const dialog = page.locator('.dialog-card')
        const box = await dialog.boundingBox()
        if (!box) throw new Error('dialog not visible')
        await page.mouse.move(box.x + box.width / 2, box.y + 20)
        await page.mouse.down()
        await page.mouse.move(5, 5)
        await page.mouse.up()
        expect(await dialog.count()).toBe(1)
        await page.mouse.click(5, 5)
        await dialog.waitFor({ state: 'detached' })
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
