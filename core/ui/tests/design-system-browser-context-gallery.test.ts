// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(深浅主题检查上下文表单和零优先级保存)。
describe('context settings gallery browser', () => {
  it('edits zero priority in both themes without touching real settings', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreSettings')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const card = page.locator('.setting-card').filter({ hasText: '全局上下文加载' })
        const input = card.locator('.lc-priority'); await input.fill('0')
        await card.getByRole('button', { name: '保存', exact: true }).click()
        expect(await page.locator('.preview').innerText()).toContain('本地优先级：0')
        expect(await input.inputValue()).toBe('0')
        expect(await card.getByRole('button', { name: '移除 AGENTS.md' }).count()).toBe(1)
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
