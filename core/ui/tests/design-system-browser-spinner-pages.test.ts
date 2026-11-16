// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('page loading motion', () => {
  it('shares rotation across model, plugin and call pages without changing speed', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/spinner-pages.ts' })
      const selectors = ['[data-model-probe] svg', '[data-plugin-refresh] svg', '.dc-icon-btn svg']
      for (const selector of selectors) await page.locator('#spinner-page-fixture').locator(selector).first().waitFor()
      const model = page.locator('#spinner-page-fixture [data-model-probe] svg')
      const plugin = page.locator('#spinner-page-fixture [data-plugin-refresh] svg')
      const direct = page.locator('#spinner-page-fixture .dc-icon-btn svg').first()
      for (const [icon, duration] of [[model, '1s'], [plugin, '1s'], [direct, '0.9s']] as const) {
        expect(await icon.evaluate(el => getComputedStyle(el).animationName)).toBe('sunday-spin')
        expect(await icon.evaluate(el => getComputedStyle(el).animationDuration)).toBe(duration)
      }
      await page.emulateMedia({ reducedMotion: 'reduce' })
      for (const icon of [model, plugin, direct]) expect(await icon.evaluate(el => getComputedStyle(el).animationName)).toBe('none')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
