// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('model catalog geometry', () => {
  it('uses the shared card and control radii while preserving model inspection', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0, strictPort: false } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(5000)
      page.setDefaultNavigationTimeout(60000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreModelCatalog')
      const card = page.locator('[data-model-card="example-model"]')
      expect(await card.evaluate(element => getComputedStyle(element).borderRadius)).toBe('12px')
      await page.locator('.mc-spark-slot').first().hover()
      expect(await page.locator('.mc-spark-tip').evaluate(element => getComputedStyle(element).borderRadius)).toBe('6px')
      await card.click()
      const providerButton = page.locator('.mc-insp-provider-btn')
      await providerButton.waitFor({ state: 'visible' })
      expect(await providerButton.evaluate(element => getComputedStyle(element).borderRadius)).toBe('6px')
      await page.getByLabel('显示示例模型').uncheck()
      expect(await page.locator('.mc-shelf-empty').evaluate(element => getComputedStyle(element).borderRadius)).toBe('12px')
      await page.locator('[data-model-catalog-view="group"]').click()
      expect(await page.locator('.mc-group-new').evaluate(element => getComputedStyle(element).borderRadius)).toBe('6px')
      await page.getByLabel('显示示例供应商').uncheck()
      expect(await page.locator('.mc-preset').first().evaluate(element => getComputedStyle(element).borderRadius)).toBe('12px')
      await page.close()
    } finally {
      await browser.close()
      await server.close()
    }
  }, 90000)
})
