// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('open select becoming disabled', () => {
  it('closes its floating menu and prevents selection', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('UiSelect')
      const select = page.getByLabel('示例选项')
      await select.click()
      expect(await page.locator('.ui-select-menu').count()).toBe(1)
      await page.getByLabel('禁用支持此状态的控件').evaluate((el: HTMLInputElement) => el.click())
      expect(await page.locator('.ui-select-menu').count()).toBe(0)
      expect(await select.isDisabled()).toBe(true)
      expect(await select.getAttribute('aria-expanded')).toBe('false')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
