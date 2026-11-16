// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(浏览器导航和外部打开仅作用于展厅内存)。
describe('split browser gallery', () => {
  it('validates and simulates navigation, external open and failure', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreSplitBrowser')
      const field = page.getByRole('textbox', { name: '网页地址' })
      await field.fill('javascript:alert(1)'); await field.press('Enter')
      expect(await page.getByRole('alert').innerText()).toContain('仅支持 HTTP 或 HTTPS')
      await field.fill('example.invalid'); await field.press('Enter')
      expect(await page.locator('.preview').innerText()).toContain('本地导航：https://example.invalid/')
      await page.getByRole('button', { name: '在默认浏览器打开' }).click()
      expect(await page.locator('.preview').innerText()).toContain('本地外部打开：https://example.invalid/')
      await page.getByLabel('模拟导航失败').check(); await field.fill('other.invalid'); await field.press('Enter')
      expect(await page.getByRole('alert').innerText()).toContain('示例导航失败')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
