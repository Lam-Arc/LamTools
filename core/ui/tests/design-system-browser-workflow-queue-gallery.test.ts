// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(真实浏览器核对队列标签焦点及清理确认)。
describe('workflow queue gallery browser', () => {
  it('supports keyboard tabs and local clear in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('WorkflowQueuePanel')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const queue = page.getByRole('tab', { name: '当前队列' }); const history = page.getByRole('tab', { name: '运行历史' })
        await queue.focus(); await page.keyboard.press('ArrowRight')
        expect(await history.getAttribute('aria-selected')).toBe('true')
        expect(await history.evaluate(el => document.activeElement === el)).toBe(true)
        await page.getByRole('button', { name: '清理历史' }).click()
        await page.getByRole('button', { name: '确认清理' }).click()
        expect(await page.locator('.wf-queue-empty').innerText()).toContain('还没有运行历史')
        await page.locator('[data-workflow-queue-reset]').click()
        await queue.click()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
