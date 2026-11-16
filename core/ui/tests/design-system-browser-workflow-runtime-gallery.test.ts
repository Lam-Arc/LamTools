// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(核对工作流状态、主题及减少动态效果)。
describe('workflow runtime gallery browser', () => {
  it('shows real running and failed states in both themes and honors reduced motion', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('WorkflowNodeRuntimeDock')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const icon = page.locator('.wf-node-runtime .sunday-spin')
        expect(await icon.evaluate(el => getComputedStyle(el).animationDuration)).toBe('0.8s')
        await page.emulateMedia({ reducedMotion: 'reduce' })
        expect(await icon.evaluate(el => getComputedStyle(el).animationName)).toBe('none')
        await page.emulateMedia({ reducedMotion: 'no-preference' })
        await page.locator('[data-workflow-runtime-state="error"]').click()
        expect(await page.locator('.wf-node-runtime').innerText()).toContain('示例错误')
        await page.locator('[data-workflow-runtime-state="running"]').click()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
