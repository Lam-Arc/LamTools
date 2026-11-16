// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('modal keyboard containment', () => {
  it('keeps Tab and Shift+Tab within each shared modal', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1000, height: 800 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(15000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      for (const [name, opener] of [['LibraryConfirmDialog', '[data-library-confirm-open]'], ['LibraryNameDialog', '[data-library-name-open]'], ['CoreConfirmDialog', '[data-open-confirm]']]) {
        await page.getByLabel('搜索组件').fill(name)
        await page.locator(opener).click()
        const dialog = page.getByRole('dialog').first()
        await dialog.waitFor()
        for (const key of ['Tab', 'Tab', 'Tab', 'Tab', 'Shift+Tab', 'Shift+Tab', 'Shift+Tab', 'Shift+Tab']) {
          await page.keyboard.press(key)
          expect(await dialog.evaluate(el => el.contains(document.activeElement)), `${name} after ${key}`).toBe(true)
        }
        await page.keyboard.press('Escape')
        await dialog.waitFor({ state: 'hidden' })
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
