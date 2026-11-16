// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(用真实浏览器核对附件组合与主题)。
describe('attachment tray gallery browser', () => {
  it('keeps attachment layout and local interactions in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('AttachmentTray')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click()
        await page.getByRole('button', { name: theme, exact: true }).click()
        const columns = page.locator('.attachment-column')
        expect(await columns.count()).toBe(2)
        expect(await columns.first().evaluate(el => getComputedStyle(el).height)).toBe('104px')
        await page.locator('[data-attachment-preview="gallery-document"]').click()
        await expectText(page.locator('.preview'), '预览：gallery-document')
        await page.locator('[data-attachment-retry="gallery-failed"]').click()
        expect(await page.locator('[data-attachment-retry="gallery-failed"]').count()).toBe(0)
        await page.locator('[data-attachment-reset]').click()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
async function expectText(locator: import('playwright').Locator, text: string) {
  expect(await locator.innerText()).toContain(text)
}
