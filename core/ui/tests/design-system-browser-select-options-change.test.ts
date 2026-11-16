// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('live select option changes', () => {
  it('keeps keyboard focus available when the focused option becomes disabled', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('UiSelect')
      await page.getByLabel('示例选项').click()
      const options = page.locator('.ui-select-menu .ui-select-option')
      await options.nth(1).focus()
      await page.getByLabel('禁用第二项').evaluate((el: HTMLInputElement) => el.click())
      expect(await options.first().evaluate(el => document.activeElement === el)).toBe(true)
      expect(await options.nth(1).isDisabled()).toBe(true)
      await page.keyboard.press('ArrowDown')
      expect(await options.nth(2).evaluate(el => document.activeElement === el)).toBe(true)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
