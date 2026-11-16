// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(核对插件动作失败、保留输入与本地授权)。
describe('plugin region gallery browser', () => {
  it('retains failed inputs and responds to local consent in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } }); page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('PluginRegionBlocks')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        await page.locator('[data-action="sample-run"]').click()
        const input = page.locator('.plugin-action-form input[type="text"]'); await input.fill('保留数据')
        await page.locator('[data-region-fail]').check(); await page.locator('.plugin-action-form').getByRole('button', { name: '执行' }).click()
        expect(await page.locator('.plugin-action-error').innerText()).toContain('示例执行失败')
        expect(await input.inputValue()).toBe('保留数据')
        await page.locator('[data-region-fail]').uncheck(); await page.locator('.plugin-action-form').getByRole('button', { name: '执行' }).click()
        await page.getByRole('dialog').getByRole('button', { name: theme === '深色' ? '确认' : '取消' }).click()
        expect(await page.locator('.preview').innerText()).toContain(theme === '深色' ? '本地授权：approve' : '本地授权：deny')
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
