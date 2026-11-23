// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(加速与网站检查只在内存中模拟)。
it('exercises acceleration, site checking and navigation in isolation', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('NetworkDashboard')
    await page.getByRole('button', { name: '一键加速' }).click()
    expect(await page.locator('.nx-accel-control').innerText()).toContain('本机加速中')
    await page.getByRole('button', { name: 'google.com', exact: true }).click()
    expect(await page.getByLabel('要检查的网站').inputValue()).toBe('google.com')
    await page.getByRole('button', { name: '检查一下' }).click()
    expect(await page.locator('.preview').innerText()).toContain('本地检查：google.com')
    await page.getByRole('button', { name: '去代理页管理' }).click()
    expect(await page.locator('.preview').innerText()).toContain('本地导航：proxy')
    await page.getByLabel('模拟处理中').check()
    expect(await page.getByRole('button', { name: '检查一下' }).isDisabled()).toBe(true)
    expect(await page.locator('[data-source-path="core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/DashboardView.vue"]').count()).toBe(1)
  } finally { await browser.close(); await server.close() }
}, 120000)
