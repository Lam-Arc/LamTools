// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('source inventory navigation', () => {
  it('finds a nested preview and focuses its real specimen', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('RightSidebarChecklist')
      expect(await page.locator('.right-sidebar-checklist').count()).toBe(1)
      await page.getByLabel('组件分类').click()
      await page.getByRole('button', { name: '输入', exact: true }).click()
      expect(await page.locator('.right-sidebar-checklist').count()).toBe(0)
      await page.locator('[data-show-inventory]').click()
      await page.locator('[data-inventory-path="core/ui/src/components/RightSidebarChecklist.vue"] button').click()
      expect(await page.getByLabel('搜索组件').inputValue()).toBe('RuntimeChecklistCard')
      expect(await page.locator('#specimen-RuntimeChecklistCard').evaluate(el => document.activeElement === el)).toBe(true)
      await page.locator('[data-source="RuntimeChecklistCard"]').click()
      expect(await page.locator('[data-source-content="RuntimeChecklistCard"]').textContent()).toContain('RightSidebarChecklist.vue')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
