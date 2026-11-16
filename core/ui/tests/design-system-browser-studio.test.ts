// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('studio floating menu', () => {
  it('allows clicking the shared menu above the full-screen editor', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0, strictPort: false } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/studio.ts' })
      await page.locator('[data-studio-open-layers]').waitFor()
      await page.locator('[data-studio-open-layers]').click()
      await page.locator('[data-studio-view="elements"]').click()
      await page.locator('[data-studio-node="shell.sidebar"]').click()
      await page.locator('[data-studio-open-props]').click()
      await page.locator('[data-studio-color-token] .ui-select-trigger').click()
      const option = page.locator('.ui-select-menu .ui-select-option').getByText('透明', { exact: true })
      await option.click()
      expect(await page.locator('[data-studio-color-token] .ui-select-trigger').innerText()).toBe('透明')
      await page.close()
    } finally {
      await browser.close()
      await server.close()
    }
  })
})
