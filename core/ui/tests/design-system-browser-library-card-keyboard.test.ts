// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(真实浏览器中回车打开菜单而不进入卡片)。
describe('library card menus in the browser', () => {
  it('activates nested menus in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      for (const theme of ['深色', '浅色']) {
        const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
        await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
        await page.getByLabel('搜索组件').fill('MemoryView')
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        await page.locator('[data-memory-tier="global"]').click()
        const memory = page.locator('[data-memory-entry] .card-menu-btn'); await memory.focus(); await memory.press('Enter')
        expect(await page.locator('[data-memory-entry]').count()).toBe(1)
        await page.locator('[data-memory-menu]').waitFor({ state: 'visible' })
        await page.getByLabel('搜索组件').fill('PlanLibraryView')
        const plan = page.locator('[data-library-entry] .card-menu-btn'); await plan.focus(); await plan.press('Enter')
        expect(await page.locator('[data-library-entry]').count()).toBe(1)
        await page.locator('[data-library-menu]').waitFor({ state: 'visible' })
        await page.close()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
