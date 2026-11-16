// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('model editor switch semantics', () => {
  it('provides independent, operable switches without nested labels', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ reducedMotion: 'reduce' })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreModelCatalog')
      await page.locator('[data-model-card="example-model"]').click()
      await page.locator('[data-model-edit]').click()
      const fields = page.locator('.mc-field--switch')
      expect(await fields.count()).toBe(2)
      expect(await fields.evaluateAll(nodes => nodes.map(node => node.tagName))).toEqual(['DIV', 'DIV'])
      const thinking = fields.getByRole('switch', { name: '推理' })
      await thinking.check()
      expect(await thinking.isChecked()).toBe(true)
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
