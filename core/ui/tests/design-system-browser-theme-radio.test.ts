// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('theme area keyboard preview', () => {
  it('navigates styled radio groups in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('ThemeAreaEditor')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click()
        await page.getByRole('button', { name: theme, exact: true }).click()
        const solid = page.locator('[data-theme-fill-mode="solid"]')
        await solid.click(); await solid.focus(); await page.keyboard.press('ArrowRight')
        const gradient = page.locator('[data-theme-fill-mode="gradient"]')
        expect(await gradient.getAttribute('aria-checked')).toBe('true')
        expect(await gradient.evaluate(el => document.activeElement === el)).toBe(true)
        expect(await gradient.evaluate(el => getComputedStyle(el).borderRadius)).not.toBe('0px')
        const glass = page.locator('[data-theme-glass-level="off"]')
        await glass.focus(); await page.keyboard.press('End')
        expect(await page.locator('[data-theme-glass-level="low"]').getAttribute('aria-checked')).toBe('true')
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
