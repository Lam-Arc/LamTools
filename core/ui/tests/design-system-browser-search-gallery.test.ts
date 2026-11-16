// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(真实搜索预览的焦点、键盘与主题)。
describe('search gallery browser', () => {
  it('keeps gallery focus and activates a local result in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      const filter = page.getByLabel('搜索组件'); await filter.fill('SearchShell')
      const search = page.locator('.search-field-input'); await search.waitFor()
      expect(await filter.evaluate(el => document.activeElement === el)).toBe(true)
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        await search.focus()
        const active = await search.getAttribute('aria-activedescendant')
        expect(active).toBeTruthy()
        expect(await page.locator(`[id="${active}"]`).getAttribute('aria-selected')).toBe('true')
        await page.keyboard.press('Enter')
        expect(await page.locator('.preview').innerText()).toContain('本地打开：sample-session')
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
