// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('library confirmation preview', () => {
  it('renders the full warning and safely restores keyboard focus', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1000, height: 700 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('LibraryConfirmDialog')
      const opener = page.locator('[data-library-confirm-open]')
      await opener.click()
      const dialog = page.getByRole('dialog', { name: '删除示例' })
      await dialog.waitFor()
      const info = await dialog.evaluate(el => {
        const text = el.querySelector('.dialog-text') as HTMLElement
        const rect = el.getBoundingClientRect()
        return { width: Math.round(rect.width), background: getComputedStyle(el).backgroundColor, fullText: text.scrollHeight <= text.clientHeight, focus: document.activeElement?.textContent }
      })
      expect(info.width).toBeGreaterThanOrEqual(390)
      expect(info.width).toBeLessThanOrEqual(402)
      expect(info.background).not.toBe('rgba(0, 0, 0, 0)')
      expect(info.fullText).toBe(true)
      expect(info.focus).toBe('取消')
      await page.keyboard.press('Escape')
      await dialog.waitFor({ state: 'hidden' })
      expect(await opener.evaluate(el => document.activeElement === el)).toBe(true)
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
