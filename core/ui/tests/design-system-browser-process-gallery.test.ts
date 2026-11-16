// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('process gallery preview', () => {
  it('exercises local logs and state in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1100, height: 800 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('RightSidebarProcesses')
      const process = page.locator('[data-process-pid="42"]')
      await process.locator('.core-process-panel__main').click()
      expect(await process.textContent()).toContain('示例标准输出')
      await process.getByRole('tab', { name: '错误输出' }).click()
      expect(await process.textContent()).toContain('示例错误输出')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click()
        await page.getByRole('button', { name: theme, exact: true }).click()
        expect(await process.locator('.core-process-panel__main').evaluate(el => getComputedStyle(el).display)).not.toBe('none')
      }
      await process.getByRole('button', { name: '终止进程 42' }).click()
      await page.getByText('已退出', { exact: true }).waitFor()
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
