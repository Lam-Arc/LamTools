// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('indeterminate progress', () => {
  it('visibly indicates unknown progress and respects reduced motion', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1100, height: 800 }, reducedMotion: 'no-preference' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('SundayProgress')
      await page.getByLabel('模拟未知总量').check()
      const bar = page.getByRole('progressbar', { name: '示例进度' })
      expect(await bar.getAttribute('aria-valuenow')).toBeNull()
      expect(await bar.getAttribute('aria-valuetext')).toBe('处理中')
      const fill = bar.locator('.sunday-progress__fill')
      expect(await fill.evaluate(el => getComputedStyle(el).animationName)).toBe('sunday-progress-indeterminate')
      const widths = await bar.evaluate(el => ({ track: el.getBoundingClientRect().width, fill: el.querySelector('.sunday-progress__fill')!.getBoundingClientRect().width }))
      expect(widths.fill).toBeGreaterThan(0)
      expect(widths.fill).toBeLessThan(widths.track)
      await page.emulateMedia({ reducedMotion: 'reduce' })
      expect(await fill.evaluate(el => getComputedStyle(el).animationName)).toBe('none')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
