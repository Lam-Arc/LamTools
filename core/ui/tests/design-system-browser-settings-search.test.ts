// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('settings search previews', () => {
  it('keeps sizing, filtering and theme colors in real mode and model pages', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreLoadToolsEditor')
      const mode = page.getByLabel('搜索模式')
      const tool = page.getByLabel('搜索工具')
      await mode.waitFor()
      const backgrounds: string[] = []
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click()
        await page.getByRole('button', { name: theme, exact: true }).click()
        expect(await mode.evaluate(el => getComputedStyle(el).fontSize)).toBe('12px')
        expect(await mode.locator('..').evaluate(el => getComputedStyle(el).minHeight)).toBe('36px')
        backgrounds.push(await mode.locator('..').evaluate(el => getComputedStyle(el).backgroundColor))
        await mode.fill('execute')
        expect(await page.locator('.mode-picker-item').count()).toBe(1)
        await mode.fill('')
        await tool.fill('不存在')
        expect(await page.locator('.tool-empty').count()).toBe(1)
        await tool.fill('')
      }
      expect(backgrounds[0]).not.toBe(backgrounds[1])
      await page.getByLabel('搜索组件').fill('CoreModelCatalog')
      const model = page.getByLabel('搜索模型或供应商')
      await model.waitFor()
      expect(await model.evaluate(el => getComputedStyle(el).fontSize)).toBe('11.5px')
      expect(await model.locator('..').evaluate(el => getComputedStyle(el).height)).toBe('32px')
      await model.fill('不存在')
      expect(await page.locator('[data-model-card="example-model"]').count()).toBe(0)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
