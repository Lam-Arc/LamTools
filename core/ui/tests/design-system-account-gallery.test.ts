// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(配对和复制均为本地模拟，不启动服务或修改剪贴板)。
it('previews desktop pairing and failure states in isolation', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('AccountShell')
    await page.getByRole('button', { name: '生成配对二维码' }).click()
    expect(await page.locator('[data-remote-ticket]').innerText()).toBe('sunday1:example')
    expect(await page.locator('[data-p2p-service-status]').innerText()).toContain('秒后失效')
    await page.getByRole('button', { name: '复制票据' }).click()
    expect(await page.locator('.preview').innerText()).toContain('本地复制：sunday1:example')
    await page.getByRole('button', { name: '停止接受' }).click()
    expect(await page.getByRole('button', { name: '生成配对二维码' }).count()).toBe(1)
    await page.getByLabel('模拟生成失败').check()
    await page.getByRole('button', { name: '生成配对二维码' }).click()
    expect(await page.getByRole('alert').innerText()).toContain('示例服务失败')
  } finally { await browser.close(); await server.close() }
}, 120000)
