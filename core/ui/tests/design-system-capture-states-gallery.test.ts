// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“实时预览、参数调整、变体对比”+(截图发送中和错误状态可在展厅切换)。
it('previews capture busy and error states', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 900 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('CaptureEditor')
    await page.locator('[data-load-capture]').click()
    await page.getByLabel('模拟截图发送中').check()
    expect(await page.getByRole('button', { name: '发送中' }).isDisabled()).toBe(true)
    await page.getByLabel('模拟截图错误').check()
    expect(await page.locator('.capture__error').innerText()).toContain('示例发送失败')
    await page.getByLabel('模拟截图发送中').uncheck()
    expect(await page.getByRole('button', { name: '发送', exact: true }).isEnabled()).toBe(true)
  } finally { await browser.close(); await server.close() }
}, 120000)
