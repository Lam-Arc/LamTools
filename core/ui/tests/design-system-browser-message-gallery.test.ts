// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(真实浏览器检查消息在深浅主题下的呈现和展开)。
describe('message gallery browser', () => {
  it('shows user and assistant messages and expands a long message in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('MessageView')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const bubble = page.locator('.user-bubble'); await bubble.waitFor()
        const answer = page.locator('.assistant-answer').first()
        expect(await answer.innerText()).toContain('示例回答')
        const fold = page.locator('[data-user-bubble-fold]')
        expect(await fold.getAttribute('aria-expanded')).toBe('false')
        await fold.click(); expect(await fold.getAttribute('aria-expanded')).toBe('true')
        expect((await bubble.boundingBox())!.height).toBeGreaterThan(0)
        await fold.click()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
