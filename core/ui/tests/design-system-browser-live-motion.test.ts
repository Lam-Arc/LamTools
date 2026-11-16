// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('live message motion', () => {
  it('stops message and process entry motion when reduced motion is requested', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/live-motion.ts' })
      for (const selector of ['.assistant-message--live', '.process-stream--live']) {
        expect(await page.locator(selector).evaluate(el => getComputedStyle(el).animationName)).toBe('none')
        await page.emulateMedia({ reducedMotion: 'no-preference' })
        expect(await page.locator(selector).evaluate(el => getComputedStyle(el).animationName)).toBe('stream-enter')
        await page.emulateMedia({ reducedMotion: 'reduce' })
      }
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
