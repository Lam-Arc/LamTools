// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(核对插件市场失败、重试和深浅主题)。
describe('plugin market gallery browser', () => {
  it('simulates failure and installation in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('PluginMarket')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const action = page.locator('[data-market-action="sample"]'); await action.waitFor()
        await page.locator('[data-market-fail]').check(); await action.click()
        expect(await page.locator('.market-error').innerText()).toContain('示例安装失败')
        await page.locator('[data-market-fail]').uncheck(); await action.click()
        expect(await action.isDisabled()).toBe(true)
        expect(await action.innerText()).toContain('已安装')
        await page.locator('[data-market-reset]').click()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
