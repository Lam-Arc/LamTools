// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(核对消息运行过程与历史展开状态)。
describe('message process browser', () => {
  it('expands completed process and shows the running variant in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('MessageView')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const sample = page.locator('[data-gallery-process]'); const toggle = sample.locator('.process-summary')
        await toggle.waitFor(); expect(await toggle.getAttribute('aria-expanded')).toBe('false')
        await toggle.click(); expect(await toggle.getAttribute('aria-expanded')).toBe('true')
        expect(await sample.locator('.process-stream').count()).toBe(1)
        await page.locator('[data-message-live]').check()
        expect(await sample.locator('.process-stream--live').count()).toBe(1)
        await page.locator('[data-message-live]').uncheck(); await toggle.click()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
