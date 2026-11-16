// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(模型与权限选择只更改展厅本地状态)。
describe('execution controls gallery', () => {
  it('changes local permission and model, and closes menus on disable', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreExecutionControls')
      const runtime = page.locator('.core-runtime-menu__trigger'); await runtime.click()
      await page.locator('[data-runtime-section="permission"]').click()
      await page.locator('[data-runtime-permission-option="auto"]').click()
      expect(await page.locator('.preview').innerText()).toContain('本地权限：auto')
      await page.locator('.core-workspace-menu__trigger').click()
      await page.waitForFunction(() => document.activeElement?.getAttribute('data-workspace-option') === 'workspace-a')
      await page.keyboard.press('ArrowDown')
      const remote = page.locator('[data-workspace-option="workspace-b"]')
      expect(await remote.evaluate(el => document.activeElement === el)).toBe(true)
      await remote.press('Enter')
      expect(await page.locator('.preview').innerText()).toContain('本地环境：workspace-b')
      const model = page.locator('.core-model-thinking-menu__trigger'); await model.click()
      await page.locator('[data-model-thinking-model-option="model-b"]').click()
      expect(await page.locator('.preview').innerText()).toContain('本地模型：model-b')
      await page.getByLabel('禁用执行选项').check()
      expect(await page.locator('[data-model-thinking-card]').count()).toBe(0)
      expect(await model.isDisabled()).toBe(true)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
