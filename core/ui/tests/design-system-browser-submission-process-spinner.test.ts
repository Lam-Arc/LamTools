// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('submission and process loading feedback', () => {
  it('uses shared animation with original speeds and reduced motion', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreSubmissionStatus')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/spinner-process.ts' })
      const submission = page.locator('.submission-status__icon svg')
      const process = page.locator('#process-spinner-fixture .core-process-panel__refresh svg')
      for (const [icon, duration] of [[submission, '0.9s'], [process, '1s']] as const) {
        expect(await icon.evaluate(el => getComputedStyle(el).animationName)).toBe('sunday-spin')
        expect(await icon.evaluate(el => getComputedStyle(el).animationDuration)).toBe(duration)
      }
      await page.emulateMedia({ reducedMotion: 'reduce' })
      for (const icon of [submission, process]) expect(await icon.evaluate(el => getComputedStyle(el).animationName)).toBe('none')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
