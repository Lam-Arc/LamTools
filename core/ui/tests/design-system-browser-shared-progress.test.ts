// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('shared plugin progress appearance', () => {
  it('uses control fill in both themes while keeping the compact sidebar height', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1100, height: 800 }, reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/progress.ts' })
      const host = page.locator('#progress-fixture')
      const plugin = host.getByRole('progressbar', { name: '插件进度' })
      const sidebar = host.getByRole('progressbar', { name: '侧栏进度' })
      for (const fill of ['rgb(250, 247, 240)', 'rgb(40, 40, 40)']) {
        await host.evaluate((el, color) => (el as HTMLElement).style.setProperty('--settings-control-solid', color), fill)
        for (const bar of [plugin, sidebar]) {
          expect(await bar.locator('.sunday-progress__fill').evaluate(el => getComputedStyle(el).backgroundColor)).toBe(fill)
          expect(await bar.getAttribute('aria-valuenow')).toBe('50')
          expect(await bar.locator('.sunday-progress__fill').evaluate(el => getComputedStyle(el).transitionDuration)).toBe('0s')
        }
        expect(await sidebar.evaluate(el => el.getBoundingClientRect().height)).toBe(4)
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
