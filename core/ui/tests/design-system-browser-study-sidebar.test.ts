// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('study sidebar preview', () => {
  it('uses the actual navigation styles and remains operable in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1100, height: 800 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('StudySidebar')
      const sidebar = page.locator('.study-sidebar-preview')
      const action = sidebar.getByRole('button', { name: '管理你的知识' })
      expect(await action.evaluate(el => getComputedStyle(el).minHeight)).toBe('34px')
      await page.getByLabel('模拟加载失败').check()
      await sidebar.getByRole('button', { name: '展开 示例课程' }).click()
      expect(await sidebar.getByRole('alert').textContent()).toContain('加载失败')
      await page.getByLabel('模拟加载失败').uncheck()
      await sidebar.getByRole('button', { name: '重试' }).click()
      await sidebar.getByRole('button', { name: '示例知识点' }).click()
      expect(await page.locator('[data-study-preview-result]').textContent()).toContain('示例知识点')
      const dark = await sidebar.evaluate(el => getComputedStyle(el).backgroundColor)
      await page.getByLabel('预览主题').click()
      await page.getByRole('button', { name: '浅色', exact: true }).click()
      expect(await sidebar.evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe(dark)
      await page.getByLabel('显示笔记入口').uncheck()
      expect(await sidebar.getByRole('button', { name: '笔记', exact: true }).count()).toBe(0)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
