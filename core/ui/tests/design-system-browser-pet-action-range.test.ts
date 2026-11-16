// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('pet behavior range rendering', () => {
  it('shows full-width shared tracks and meaningful values in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/pet-action.ts' })
      const range = page.locator('#pet-action-fixture').getByRole('slider', { name: '活动频率' })
      expect(await range.getAttribute('aria-valuetext')).toBe('50%')
      for (const label of ['深色', '浅色']) {
        await page.locator('[data-gallery-theme] .ui-select-trigger').click()
        await page.locator('.ui-select-menu .ui-select-option').getByText(label, { exact: true }).click()
        const layout = await range.evaluate(el => ({ width: el.getBoundingClientRect().width, fill: getComputedStyle(el.parentElement!.querySelector('.sunday-range__fill')!).backgroundColor }))
        expect(layout.width).toBeGreaterThan(100)
        expect(layout.fill).not.toBe('rgba(0, 0, 0, 0)')
      }
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
