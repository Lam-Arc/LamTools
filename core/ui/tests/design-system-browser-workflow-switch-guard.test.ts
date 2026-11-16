// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(真实浏览器核对草稿对话框焦点与三种选择)。
describe('workflow draft dialog browser', () => {
  it('traps and restores focus while preserving the three choices', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('WorkflowSwitchGuard')
      const opener = page.locator('[data-workflow-guard-open]')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        await opener.click()
        const dialog = page.getByRole('dialog'); const cancel = dialog.getByRole('button', { name: '取消' }); const save = dialog.getByRole('button', { name: '保存并切换' })
        expect(await cancel.evaluate(el => document.activeElement === el)).toBe(true)
        await cancel.focus(); await page.keyboard.press('Shift+Tab')
        expect(await save.evaluate(el => document.activeElement === el)).toBe(true)
        await page.keyboard.press('Escape')
        expect(await dialog.count()).toBe(0)
        expect(await opener.evaluate(el => document.activeElement === el)).toBe(true)
        await opener.click(); await page.getByRole('button', { name: '放弃修改' }).click()
        expect(await page.locator('.preview').innerText()).toContain('discard')
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
