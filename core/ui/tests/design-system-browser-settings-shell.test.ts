// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('settings shell gallery browser', () => {
  it('keeps real navigation and content usable in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('SettingsShell')
      const shell = page.locator('.settings-shell-preview .settings-page')
      const nav = shell.locator('.settings-sidebar')
      const main = shell.locator('.settings-main')
      const dimensions = await shell.evaluate(el => {
        const nav = el.querySelector('.settings-sidebar')!.getBoundingClientRect()
        const main = el.querySelector('.settings-main')!.getBoundingClientRect()
        return { nav: nav.width, main: main.width, gap: main.left - nav.right }
      })
      expect(dimensions.nav).toBeGreaterThan(60)
      expect(dimensions.main).toBeGreaterThan(200)
      expect(dimensions.gap).toBeGreaterThanOrEqual(0)
      const dark = await main.evaluate(el => getComputedStyle(el).color)
      await page.getByLabel('预览主题').click()
      await page.getByRole('button', { name: '浅色', exact: true }).click()
      expect(await main.evaluate(el => getComputedStyle(el).color)).not.toBe(dark)
      await nav.getByRole('button', { name: '界面' }).click()
      expect(await main.innerText()).toContain('界面示例')
      await page.getByLabel('隐藏预览导航').check()
      expect(await nav.count()).toBe(0)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
