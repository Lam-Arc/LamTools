// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
// user:“直接渲染项目真实组件，支持分类、搜索、筛选、实时预览、交互测试、参数调整、变体对比及源码定位”+(托盘操作在内存中演示，不能退出应用)。
it('previews the real tray panel without controlling the desktop', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage(); page.setDefaultTimeout(30000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('TrayPanel')
    const panel = page.getByRole('menu', { name: 'Sunday 托盘面板' })
    await panel.waitFor({ state: 'visible' })
    await panel.getByRole('menuitemcheckbox', { name: /桌宠/ }).click()
    await page.waitForFunction(() => document.querySelector('[role=menuitemcheckbox]')?.getAttribute('aria-checked') === 'true')
    await panel.getByRole('menuitem', { name: '退出' }).click()
    expect(await page.getByText('示例操作：退出').isVisible()).toBe(true)
  } finally { await browser.close(); await server.close() }
}, 120000)

