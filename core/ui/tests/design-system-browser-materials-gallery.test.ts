// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(真实浏览器验证资料标签补全和键盘焦点)。
describe('materials gallery keyboard browser', () => {
  it('completes an existing tag without opening the file in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      for (const theme of ['深色', '浅色']) {
        const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
        await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
        await page.getByLabel('搜索组件').fill('MaterialsView')
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const input = page.locator('[data-material-tag-input="sample-a"]'); await input.click(); await input.fill('but'); await input.press('ArrowDown')
        const option = page.locator('[data-material-tag-suggest="button"]')
        expect(await option.getAttribute('aria-selected')).toBe('true')
        expect(await input.getAttribute('aria-activedescendant')).toBe(await option.getAttribute('id'))
        await input.press('Enter')
        expect(await page.locator('.preview').innerText()).toContain('本地标签：button')
        expect(await input.evaluate(el => document.activeElement === el)).toBe(true)
        const star = page.locator('[data-material="sample-a"] .material-rating-star').first()
        await star.focus(); await star.press('Enter')
        expect(await page.locator('.preview').innerText()).toContain('本地评分：1')
        expect(await page.locator('.materials-view [role="alert"]').count()).toBe(0)
        await page.close()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)

  it('keeps copy-path interaction inside the preview', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage(); page.setDefaultTimeout(10000)
      await page.addInitScript(() => { Object.defineProperty(navigator, 'clipboard', { value: { writeText: async () => { (window as any).__copiedOutside = true } }, configurable: true }) })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('MaterialsView')
      await page.locator('[data-material="sample-a"] .card-menu-btn').click()
      await page.getByRole('menuitem', { name: '复制路径' }).click()
      expect(await page.evaluate(() => Boolean((window as any).__copiedOutside))).toBe(false)
      expect(await page.locator('.preview').innerText()).toContain('本地复制：')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
