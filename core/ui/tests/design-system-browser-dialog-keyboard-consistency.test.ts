// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('dialog keyboard behavior', () => {
  it('restores focus from name dialog and handles a disabled confirmation', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('LibraryNameDialog')
      const openName = page.locator('[data-library-name-open]')
      await openName.click()
      const nameCancel = page.locator('.dialog-actions button').first()
      await nameCancel.focus()
      await page.keyboard.press('Escape')
      expect(await page.locator('.dialog-card').count()).toBe(0)
      expect(await openName.evaluate(el => document.activeElement === el)).toBe(true)
      await page.getByLabel('搜索组件').fill('CoreConfirmDialog')
      await page.getByLabel('包含输入框').uncheck()
      await page.getByLabel('禁止确认').check()
      await page.locator('[data-open-confirm]').click()
      const cancel = page.locator('.core-confirm__cancel').first()
      expect(await cancel.evaluate(el => document.activeElement === el)).toBe(true)
      expect(await page.locator('.core-confirm__submit').isDisabled()).toBe(true)
      await page.keyboard.press('Escape')
      await page.locator('.core-confirm__backdrop').waitFor({ state: 'detached' })
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
