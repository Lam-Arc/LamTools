// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('shared loading motion', () => {
  it('preserves speed variants and respects reduced motion in a real sidebar', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('SundaySpinner')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/spinner.ts' })
      const variants = page.locator('.preview .sunday-spin')
      expect(await variants.count()).toBe(4)
      await page.locator('[data-source="SundaySpinner"]').click()
      expect(await page.locator('[data-source-content="SundaySpinner"]').textContent()).toContain('prefers-reduced-motion')
      expect(await variants.evaluateAll(els => els.map(el => getComputedStyle(el).animationDuration))).toEqual(['0.8s', '0.9s', '1s', '1.2s'])
      const runtime = page.locator('#spinner-fixture .sunday-spin')
      await page.locator('#spinner-fixture .right-sidebar-rag input').fill('示例')
      await page.locator('#spinner-fixture .right-sidebar-rag button').click()
      await page.locator('#spinner-fixture .right-sidebar-web-search-action').click()
      expect(await runtime.count()).toBe(6)
      expect(await runtime.evaluateAll(els => els.map(el => getComputedStyle(el).animationDuration))).toEqual(['0.9s', '0.9s', '1s', '1s', '0.8s', '0.8s'])
      expect(await runtime.evaluateAll(els => els.every(el => getComputedStyle(el).animationName === 'sunday-spin'))).toBe(true)
      await page.emulateMedia({ reducedMotion: 'reduce' })
      expect(await runtime.evaluateAll(els => els.every(el => getComputedStyle(el).animationName === 'none'))).toBe(true)
      expect(await variants.evaluateAll(els => els.every(el => getComputedStyle(el).animationName === 'none'))).toBe(true)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
