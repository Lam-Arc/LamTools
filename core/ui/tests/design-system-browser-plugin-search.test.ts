// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('plugin search preview', () => {
  it('keeps styling, search and keyboard focus in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CorePluginSystemEditor')
      const input = page.locator('[data-plugin-search]')
      await input.waitFor()
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click()
        await page.getByRole('button', { name: theme, exact: true }).click()
        expect(await input.evaluate(el => getComputedStyle(el).fontSize)).toBe('12.5px')
        expect(await input.locator('..').evaluate(el => getComputedStyle(el).minHeight)).toBe('34px')
        await input.fill('alpha')
        expect(await page.locator('.plugin-card').count()).toBe(1)
        await input.press('Escape')
        expect(await input.inputValue()).toBe('')
        expect(await input.evaluate(el => document.activeElement === el)).toBe(true)
      }
      await input.blur()
      await page.keyboard.press('/')
      expect(await input.evaluate(el => document.activeElement === el)).toBe(true)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
