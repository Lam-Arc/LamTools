// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“统一与去重…确保视觉、功能和交互不退化”+(定时任务和进程日志标签使用相同键盘行为)。
describe('shared tab keyboard navigation', () => {
  it('switches process log and schedule tabs using the keyboard', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('RightSidebarProcesses')
      await page.locator('[data-process-pid="42"] .core-process-panel__main').click()
      const out = page.getByRole('tab', { name: '标准输出' }); const err = page.getByRole('tab', { name: '错误输出' })
      expect(await out.getAttribute('tabindex')).toBe('0')
      await out.focus(); await page.keyboard.press('ArrowRight')
      expect(await err.getAttribute('aria-selected')).toBe('true')
      expect(await err.evaluate(el => document.activeElement === el)).toBe(true)
      await page.getByLabel('搜索组件').fill('CoreArrangeManager')
      await page.locator('.arrange-view .primary-button').first().click()
      const settings = page.getByRole('tab', { name: '设置' }); const history = page.getByRole('tab', { name: '历史' })
      expect(await settings.getAttribute('tabindex')).toBe('0')
      await settings.focus(); await page.keyboard.press('End')
      expect(await history.getAttribute('aria-selected')).toBe('true')
      expect(await history.evaluate(el => document.activeElement === el)).toBe(true)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
