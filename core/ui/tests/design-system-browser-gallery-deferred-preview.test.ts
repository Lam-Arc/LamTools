// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“提高前端一致性与开发效率”+(真实浏览器验证延迟加载及直接搜索)。
describe('gallery deferred previews browser', () => {
  it('loads a requested large specimen and searches another directly', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      expect(await page.locator('[data-load-preview="CoreSettings"]').count()).toBe(1)
      expect(await page.locator('[data-settings-preview-permissions]').count()).toBe(0)
      await page.locator('[data-load-preview="CoreSettings"]').click()
      await page.locator('[data-settings-preview-permissions]').waitFor()
      await page.getByLabel('搜索组件').fill('PluginMarket')
      await page.locator('[data-market-action="sample"]').waitFor()
      expect(await page.locator('[data-load-preview="PluginMarket"]').count()).toBe(0)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
