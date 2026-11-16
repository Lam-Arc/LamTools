// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(输入区以本地示例验证引用补全与发送)。
describe('composer gallery', () => {
  it('completes a reference without submitting and sends only the local draft', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('InlineFileComposer')
      const editor = page.getByRole('textbox', { name: '消息输入框' })
      await editor.fill('@笔'); await page.getByRole('option', { name: /笔记/ }).waitFor()
      await editor.press('Enter')
      expect(await page.locator('.composer-file-token').count()).toBe(1)
      expect(await page.locator('[data-gallery-composer-sent]').count()).toBe(0)
      await page.getByRole('button', { name: '发送', exact: true }).click()
      expect(await page.locator('[data-gallery-composer-sent]').innerText()).toContain('示例/笔记.md')
      expect(await page.locator('.composer-file-token').count()).toBe(0)
      expect(await page.getByRole('button', { name: '发送', exact: true }).isDisabled()).toBe(true)
      await editor.fill('#背')
      expect(await page.getByRole('option', { name: /^#背景/ }).count()).toBe(1)
      await editor.press('Enter')
      expect(await editor.innerText()).toContain('#背景')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
