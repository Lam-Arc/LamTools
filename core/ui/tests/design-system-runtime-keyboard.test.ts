// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(运行模式和权限菜单可通过键盘完整操作并恢复焦点)。
describe('runtime menu keyboard', () => {
  it('navigates both levels, selects options and returns focus', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreExecutionControls')
      const trigger = page.locator('.core-runtime-menu__trigger')
      await trigger.click()
      await expect.poll(() => page.locator('[data-runtime-section="mode"]').evaluate(el => document.activeElement === el)).toBe(true)
      await page.keyboard.press('ArrowDown')
      expect(await page.locator('[data-runtime-section="permission"]').evaluate(el => document.activeElement === el)).toBe(true)
      await page.keyboard.press('ArrowRight')
      expect(await page.locator('[data-runtime-permission-option="ask"]').evaluate(el => document.activeElement === el)).toBe(true)
      await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter')
      expect(await page.locator('.preview').innerText()).toContain('本地权限：auto')
      expect(await trigger.evaluate(el => document.activeElement === el)).toBe(true)
      await trigger.click(); await page.keyboard.press('ArrowRight')
      expect(await page.locator('[data-runtime-mode-option="normal"]').evaluate(el => document.activeElement === el)).toBe(true)
      await page.keyboard.press('End'); await page.keyboard.press('Enter')
      expect(await page.locator('.preview').innerText()).toContain('本地模式：review')
      await trigger.click(); await page.keyboard.press('Escape')
      expect(await trigger.evaluate(el => document.activeElement === el)).toBe(true)
      expect(await trigger.getAttribute('aria-expanded')).toBe('false')
    } finally { await browser.close(); await server.close() }
  }, 120000)

  it('waits for motion and never steals focus after closing', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, reducedMotion: 'no-preference' })
      page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      const search = page.getByLabel('搜索组件')
      await search.fill('CoreExecutionControls')
      const trigger = page.locator('.core-runtime-menu__trigger')
      await trigger.click()
      await expect.poll(() => page.locator('[data-runtime-section="mode"]').evaluate(el => document.activeElement === el)).toBe(true)
      await page.keyboard.press('ArrowRight')
      await expect.poll(() => page.locator('[data-runtime-mode-option="normal"]').evaluate(el => document.activeElement === el)).toBe(true)
      await search.click()
      expect(await search.evaluate(el => document.activeElement === el)).toBe(true)
      expect(await trigger.getAttribute('aria-expanded')).toBe('false')
      await trigger.click()
      await search.click()
      await page.waitForTimeout(700)
      expect(await search.evaluate(el => document.activeElement === el)).toBe(true)
      expect(await trigger.getAttribute('aria-expanded')).toBe('false')
    } finally { await browser.close(); await server.close() }
  }, 120000)
})
