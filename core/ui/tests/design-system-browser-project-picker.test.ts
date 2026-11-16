// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('project visual picker themes', () => {
  it('keeps selected indicators visible and supports keyboard choice in dark and light themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('ProjectVisualPicker')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const selected = page.locator('[data-project-icon-option="folder"]')
        await selected.click()
        const colors = await selected.evaluate(el => {
          const probe = document.createElement('span')
          probe.style.color = 'color-mix(in srgb, var(--theme-main-text) 48%, transparent)'
          el.append(probe)
          const expected = getComputedStyle(probe).color
          probe.remove()
          return { selected: getComputedStyle(el).borderColor, expected }
        })
        expect(colors.selected).toBe(colors.expected)
        await selected.focus(); await page.keyboard.press('ArrowRight')
        expect(await page.locator('[data-project-icon-option="code"]').getAttribute('aria-checked')).toBe('true')
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
