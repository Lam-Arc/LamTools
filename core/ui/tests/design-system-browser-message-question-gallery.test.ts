// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(真实浏览器核对问题卡只读和本地回答两种状态)。
describe('message question gallery browser', () => {
  it('blocks read-only answers and permits local answers in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('MessageView')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const choice = page.locator('.question-group__choice').first(); await choice.waitFor()
        expect(await choice.isDisabled()).toBe(true)
        await page.locator('[data-message-readonly]').uncheck()
        expect(await choice.isEnabled()).toBe(true)
        if (await choice.getAttribute('aria-pressed') === 'false') await choice.click()
        expect(await choice.getAttribute('aria-pressed')).toBe('true')
        expect(await page.locator('[data-question-submit]').isEnabled()).toBe(true)
        await page.locator('[data-message-readonly]').check()
        expect(await page.locator('[data-question-submit]').isDisabled()).toBe(true)
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
