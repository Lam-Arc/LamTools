// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(文件树键盘浏览与打开只操作展厅示例)。
describe('split file tree gallery', () => {
  it('navigates folders and files by keyboard', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreSplitFileTree')
      const tree = page.getByRole('tree', { name: '项目文件' })
      const folder = tree.getByRole('treeitem', { name: '示例目录' }); await folder.focus()
      expect(await tree.locator('[role="treeitem"][tabindex="0"]').count()).toBe(1)
      await folder.press('ArrowRight'); expect(await folder.getAttribute('aria-expanded')).toBe('true')
      await folder.press('ArrowRight')
      const file = tree.getByRole('treeitem', { name: '笔记.md' })
      expect(await file.evaluate(el => document.activeElement === el)).toBe(true)
      await file.press('Enter')
      expect(await page.locator('.preview').innerText()).toContain('本地打开：示例目录/笔记.md')
      await file.press('ArrowLeft'); expect(await folder.evaluate(el => document.activeElement === el)).toBe(true)
      await folder.press('ArrowLeft'); expect(await folder.getAttribute('aria-expanded')).toBe('false')
      await folder.press('End')
      const last = tree.getByRole('treeitem', { name: '说明.txt' })
      expect(await last.evaluate(el => document.activeElement === el)).toBe(true)
      await last.press('Home'); expect(await folder.evaluate(el => document.activeElement === el)).toBe(true)
      await page.getByLabel('模拟目录读取失败').check()
      await page.getByRole('button', { name: '刷新文件树' }).click()
      expect(await page.getByRole('alert').innerText()).toContain('示例目录读取失败')
      await page.getByLabel('模拟目录读取失败').uncheck()
      await page.getByRole('alert').getByRole('button', { name: '重试' }).click()
      expect(await folder.count()).toBe(1)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
