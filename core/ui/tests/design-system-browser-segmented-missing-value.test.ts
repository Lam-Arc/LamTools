// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('segmented control missing value', () => {
  it('keeps keyboard entry and hides the old highlight', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('SundaySegmented')
      await page.getByRole('button', { name: '模拟选项缺失' }).click()
      const radios = page.getByRole('radio')
      expect(await radios.first().getAttribute('tabindex')).toBe('0')
      expect(await page.locator('.sunday-segmented__indicator').isVisible()).toBe(false)
      await radios.first().focus()
      await page.keyboard.press('ArrowRight')
      expect(await radios.nth(1).getAttribute('aria-checked')).toBe('true')
      expect(await page.locator('.sunday-segmented__indicator').isVisible()).toBe(true)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
