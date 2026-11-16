// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('update modal keyboard focus', () => {
  it('focuses the card, contains Tab and restores focus in both motion modes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      for (const reducedMotion of ['reduce', 'no-preference'] as const) {
        const page = await browser.newPage({ viewport: { width: 1100, height: 800 }, reducedMotion })
        page.setDefaultTimeout(10000)
        await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
        await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/update-card.ts' })
        const opener = page.locator('#open-update-preview')
        await opener.click()
        const card = page.locator('[data-update-card]')
        await card.waitFor()
        await page.waitForFunction(() => document.querySelector('[data-update-card]')?.contains(document.activeElement))
        for (let n = 0; n < 5; n++) { await page.keyboard.press('Tab'); expect(await card.evaluate(el => el.contains(document.activeElement))).toBe(true) }
        await page.keyboard.press('Escape')
        await card.waitFor({ state: 'hidden' })
        expect(await opener.evaluate(el => document.activeElement === el)).toBe(true)
        await page.close()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
