// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(深浅主题验证插件表单、枚举和保存失败)。
describe('plugin config gallery browser', () => {
  it('edits shared controls and reports local save errors in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('PluginConfigPanel')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const panel = page.locator('.plugin-config-panel'); await panel.waitFor()
        await panel.locator('input[type="text"]').fill(`示例${theme}`)
        await panel.getByLabel('模式').click(); await page.getByRole('button', { name: 'compact', exact: true }).click()
        await panel.getByRole('button', { name: '保存配置' }).click()
        expect(await panel.locator('.config-notice').innerText()).toContain('已保存')
        await page.locator('[data-config-fail]').check(); await panel.getByRole('button', { name: '保存配置' }).click()
        expect(await panel.locator('.config-error').innerText()).toContain('示例保存失败')
        await page.locator('[data-config-fail]').uncheck()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
