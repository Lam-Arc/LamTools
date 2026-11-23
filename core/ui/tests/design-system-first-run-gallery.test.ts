// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“实时预览、交互测试、参数调整、变体对比”+(新手清单各阶段只在展厅本地切换)。
describe('first-run checklist gallery', () => {
  it('shows each stage and records its actions locally', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('FirstRunChecklist')
      const checklist = page.locator('[data-first-run]')
      expect(await checklist.getAttribute('data-first-run-stage')).toBe('provider')
      await page.getByLabel('已配置模型').check()
      expect(await checklist.getAttribute('data-first-run-stage')).toBe('workspace')
      await page.getByLabel('已有项目', { exact: true }).check()
      expect(await checklist.getAttribute('data-first-run-stage')).toBe('workspace')
      expect(await checklist.getByRole('button', { name: '开会话' }).count()).toBe(1)
      await page.getByLabel('已有会话', { exact: true }).check()
      expect(await checklist.getAttribute('data-first-run-stage')).toBe('message')
      await checklist.getByRole('button', { name: '看看这个项目里有什么' }).click()
      expect(await page.locator('.preview').innerText()).toContain('本地选择：看看这个项目里有什么')
      await page.getByLabel('已发送第一条消息').check()
      expect(await checklist.getAttribute('data-first-run-stage')).toBe('done')
      await checklist.getByRole('button', { name: '收起' }).click()
      expect(await checklist.count()).toBe(0)
    } finally { await browser.close(); await server.close() }
  }, 120000)
})
