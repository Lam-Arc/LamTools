// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(共享菜单可在展厅打开子菜单并记录本地结果)。
describe('context menu gallery', () => {
  it('navigates a real submenu and retains the menu on internal scroll', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('ContextMenuHost')
      await page.getByRole('button', { name: '打开示例菜单' }).click()
      await page.locator('[data-context-menu-panel="root"]').dispatchEvent('scroll')
      await page.getByRole('menuitem', { name: '示例子菜单' }).hover()
      await page.getByRole('menuitem', { name: '选择示例' }).click()
      expect(await page.locator('.preview').innerText()).toContain('本地选择：示例')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
