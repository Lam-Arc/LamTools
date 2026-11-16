// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(核对权限模式及目录访问状态与本地撤销)。
describe('permission settings gallery browser', () => {
  it('switches presets and enforces the full access switch state', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreSettings')
      await page.locator('[data-settings-preview-permissions]').click()
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        await page.locator('[data-default-permission-preset="full_access"]').click()
        const outside = page.locator('[data-allow-outside-workdir] input')
        expect(await outside.isChecked()).toBe(true); expect(await outside.isDisabled()).toBe(true)
        await page.locator('[data-default-permission-preset="ask"]').click()
        expect(await outside.isDisabled()).toBe(false)
      }
      await page.locator('[data-trust-revoke]').click()
      expect(await page.locator('.permissions-panel').innerText()).toContain('暂无已信任操作')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
