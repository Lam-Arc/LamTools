// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('component source directory', () => {
  it('filters by source clue and preview state, and reveals static callers', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('ThemeAreaEditor')
      await page.locator('[data-show-inventory]').click()
      const row = page.locator('[data-inventory-path="core/ui/src/components/SundayRange.vue"]')
      expect(await row.count()).toBe(1)
      await row.locator('summary').click()
      expect(await row.textContent()).toContain('core/ui/src/components/ThemeAreaEditor.vue')
      await page.getByLabel('源码线索筛选').click()
      await page.getByRole('button', { name: 'range', exact: true }).click()
      expect(await row.count()).toBe(1)
      await page.getByLabel('预览状态筛选').click()
      await page.getByRole('button', { name: '待接入预览', exact: true }).click()
      expect(await row.count()).toBe(0)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
