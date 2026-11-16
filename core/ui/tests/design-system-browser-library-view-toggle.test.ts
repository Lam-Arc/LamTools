// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('library view toggle in browser', () => {
  it('retains labelled selection and visible state in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1100, height: 800 }, reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('LibraryViewToggle')
      const grid = page.getByRole('button', { name: '网格视图' })
      const list = page.getByRole('button', { name: '列表视图' })
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click()
        await page.getByRole('button', { name: theme, exact: true }).click()
        await list.focus(); await page.keyboard.press('Enter')
        expect(await list.getAttribute('aria-pressed')).toBe('true')
        expect(await grid.getAttribute('aria-pressed')).toBe('false')
        const state = await list.evaluate(el => ({ active: getComputedStyle(el).backgroundColor, focus: getComputedStyle(el).outlineStyle }))
        expect(state.active).not.toBe('rgba(0, 0, 0, 0)')
        expect(state.focus).toBe('solid')
        await grid.click()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
