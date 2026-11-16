// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('library search preview', () => {
  it('filters local results and follows input colors in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1100, height: 800 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('LibrarySearchField')
      const search = page.getByLabel('搜索本地示例')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click()
        await page.getByRole('button', { name: theme, exact: true }).click()
        await search.fill('设计')
        expect(await page.locator('[data-library-search-example]').count()).toBe(1)
        const colors = await search.evaluate(el => ({ actual: getComputedStyle(el).color, expected: getComputedStyle(el).getPropertyValue('--theme-composer-text').trim() }))
        const expected = await search.evaluate((el, value) => { const probe = document.createElement('span'); probe.style.color = value; el.parentElement!.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color }, colors.expected)
        expect(colors.actual).toBe(expected)
        await search.fill('')
        expect(await page.locator('[data-library-search-example]').count()).toBe(3)
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
