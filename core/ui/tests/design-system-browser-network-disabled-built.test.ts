// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('distributed network select', () => {
  it('closes its menu when a pending operation disables it', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.evaluate(() => document.querySelectorAll('style, link[rel=stylesheet]').forEach(node => node.remove()))
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/network-disabled-built.ts' })
      const host = page.locator('#network-disabled-fixture')
      const select = host.locator('[data-network-quick-node] button')
      await select.click()
      expect(await page.locator('.ui-select-menu').count()).toBe(1)
      expect(await page.locator('.ui-select-menu .ui-select-option').count()).toBe(2)
      expect(await select.evaluate(el => getComputedStyle(el).height)).toBe('32px')
      await host.locator('[data-quick-action="proxy"]').evaluate((el: HTMLButtonElement) => el.click())
      await select.waitFor({ state: 'visible' })
      expect(await select.isDisabled()).toBe(true)
      expect(await page.locator('.ui-select-menu').count()).toBe(0)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
