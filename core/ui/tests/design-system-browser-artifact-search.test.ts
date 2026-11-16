// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('artifact search appearance', () => {
  it('keeps its compact styling and clear action in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('LibrarySearchField')
      const example = page.getByLabel('可清除的搜索')
      expect(await example.inputValue()).toBe('示例')
      await example.locator('..').getByRole('button', { name: '清除' }).click()
      expect(await example.inputValue()).toBe('')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/spinner.ts' })
      const input = page.locator('#spinner-fixture input[aria-label="搜索成果库"]')
      const row = page.locator('#spinner-fixture .artifact-search-row')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click()
        await page.getByRole('button', { name: theme, exact: true }).click()
        expect(await input.evaluate(el => getComputedStyle(el).fontSize)).toBe('11px')
        expect(await row.evaluate(el => getComputedStyle(el).minHeight)).toBe('32px')
        await input.fill('report')
        await page.locator('#spinner-fixture button[aria-label="清除搜索"]').click()
        expect(await input.inputValue()).toBe('')
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
