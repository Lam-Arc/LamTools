// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('pet settings theme', () => {
  it('uses the composer palette for editable fields in light and dark themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
      page.setDefaultTimeout(15000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/pet-settings-theme.ts' })
      const host = page.locator('#pet-settings-theme-fixture')
      const fields = [host.locator('.pet-settings-row input[type="number"]').first(), host.locator('.pet-settings-sector-label').first(), host.locator('.pet-settings-sector-prompt').first()]
      await fields[1].waitFor()
      for (const [background, text] of [['rgb(240, 235, 230)', 'rgb(20, 20, 20)'], ['rgb(20, 20, 20)', 'rgb(240, 235, 230)']]) {
        await host.evaluate((el, pair) => {
          const style = (el as HTMLElement).style
          style.setProperty('--theme-composer-background', pair[0])
          style.setProperty('--theme-composer-text', pair[1])
          style.setProperty('--theme-main-text', pair[1])
          style.setProperty('--theme-main-border', pair[1])
        }, [background, text])
        const expected = await host.evaluate(el => {
          const probe = document.createElement('div')
          probe.style.background = 'color-mix(in srgb, var(--theme-composer-background) 70%, transparent)'
          el.append(probe)
          const color = getComputedStyle(probe).backgroundColor
          probe.remove()
          return color
        })
        for (const field of fields) {
          const result = await field.evaluate(el => ({ bg: getComputedStyle(el).backgroundColor, text: getComputedStyle(el).color }))
          expect(result.bg).toBe(expected)
          expect(result.text).toBe(text)
        }
        expect(await host.locator('.pet-settings-sector').first().evaluate(el => getComputedStyle(el).borderColor)).toBe(text)
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
