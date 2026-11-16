// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('pending decision preview', () => {
  it('keeps an offline draft and submits it after reconnecting', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CorePendingDecisionPanel')
      await page.locator('[data-pending-decision-item="sample-question"]').click()
      await page.getByLabel('模拟通道断开').check()
      const guide = page.locator('[data-pending-decision-guide]')
      await guide.fill('先看本地预览')
      expect(await page.locator('[data-pending-decision-guide-submit]').isDisabled()).toBe(true)
      await guide.press('Enter')
      expect(await guide.inputValue()).toBe('先看本地预览')
      await page.getByLabel('模拟通道断开').uncheck()
      await guide.press('Enter')
      expect(await page.locator('[data-decision-gallery-result]').innerText()).toContain('先看本地预览')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
