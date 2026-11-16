// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('gallery source loading', () => {
  it('loads the large model catalog source only when requested and displays it', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
      const sourceRequests: string[] = []
      page.on('request', request => { if (request.url().includes('CoreModelCatalog.vue') && request.url().includes('raw')) sourceRequests.push(request.url()) })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreModelCatalog')
      expect(sourceRequests).toHaveLength(0)
      await page.locator('[data-source="CoreModelCatalog"]').click()
      await page.locator('[data-source-content="CoreModelCatalog"]').getByText('CoreModelCatalog', { exact: false }).first().waitFor()
      expect(sourceRequests).toHaveLength(1)
      await page.locator('[data-source="CoreModelCatalog"]').click()
      await page.locator('[data-source="CoreModelCatalog"]').click()
      expect(sourceRequests).toHaveLength(1)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
