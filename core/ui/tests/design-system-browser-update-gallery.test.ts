// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('update gallery states', () => {
  it('shows installation state faithfully and lets the preview end without updating', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1100, height: 800 }, reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreUpdateCard')
      await page.getByLabel('更新预览状态').click()
      await page.getByRole('button', { name: '安装中', exact: true }).click()
      await page.locator('[data-update-preview-open]').click()
      const card = page.locator('[data-update-card]')
      expect(await card.locator('[data-update-dismiss]').isDisabled()).toBe(true)
      expect(await card.locator('[data-update-confirm]').isDisabled()).toBe(true)
      await card.locator('[data-update-preview-exit]').click()
      await card.waitFor({ state: 'hidden' })
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
