// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('pet preview dropdown', () => {
  it('opens above the overlay and chooses a hitbox action', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/pet-preview.ts' })
      await page.getByRole('button', { name: 'Hitbox 编辑' }).click()
      const action = page.locator('[data-pet-preview-hitbox-action] button')
      await action.click()
      await page.locator('.ui-select-menu .ui-select-option').getByText('dance', { exact: true }).click()
      expect(await action.innerText()).toContain('dance')
    } finally { await browser.close(); await server.close() }
  }, 90000)
})
