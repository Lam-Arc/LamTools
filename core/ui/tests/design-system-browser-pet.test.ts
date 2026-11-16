// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('pet settings floating menu', () => {
  it('keeps the independent window menu clickable and updates the setting', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0, strictPort: false } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/pet.ts' })
      const trigger = page.getByRole('dialog', { name: '桌宠设置' }).getByLabel('几何精度')
      await trigger.click()
      await page.locator('.ui-select-menu .ui-select-option').getByText('高（更贴边缘）', { exact: true }).click()
      expect(await trigger.innerText()).toContain('高（更贴边缘）')
      await page.close()
    } finally {
      await browser.close()
      await server.close()
    }
  })
})
