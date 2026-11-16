// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('network settings shared dropdowns', () => {
  it('keeps form geometry and applies a DNS selection in an isolated plugin', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/network-settings.ts' })
      await page.locator('#network-settings-fixture').getByRole('button', { name: '调整 DNS' }).click()
      const field = page.locator('#network-settings-fixture .nx-form-field')
      expect(await field.evaluate(el => getComputedStyle(el).display)).toBe('grid')
      await field.getByRole('button', { name: '网络接口' }).click()
      await page.locator('.ui-select-menu .ui-select-option').getByText('以太网', { exact: true }).click()
      await page.locator('#network-settings-fixture').getByRole('button', { name: '确认并申请修改' }).click()
      expect(await page.locator('#network-settings-result').innerText()).toContain('"interface_index":4')
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
