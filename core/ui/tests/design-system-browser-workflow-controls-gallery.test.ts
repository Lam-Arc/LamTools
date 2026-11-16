// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(在深浅主题验证工作流工具栏状态与操作)。
describe('workflow controls gallery browser', () => {
  it('keeps compact controls and disabled behavior in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('WorkflowControlBar')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const run = page.getByRole('button', { name: '运行整个工作流' })
        expect(await run.evaluate(el => getComputedStyle(el).width)).toBe('28px')
        await run.click(); expect(await page.locator('.preview').innerText()).toContain('本地操作：run')
        await page.locator('[data-workflow-controls-running]').check()
        expect(await page.getByRole('button', { name: '单步调试' }).isDisabled()).toBe(true)
        await page.getByRole('button', { name: '停止工作流' }).click()
        expect(await page.locator('.preview').innerText()).toContain('本地操作：cancel')
        await page.locator('[data-workflow-controls-running]').uncheck()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
