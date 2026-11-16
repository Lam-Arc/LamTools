// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(画布使用本地工作流和独立剪贴板)。
describe('workflow canvas gallery', () => {
  it('renders and operates the real canvas without touching the system clipboard', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.addInitScript(() => { Object.defineProperty(navigator, 'clipboard', { value: { writeText: async () => { (window as any).__clipboardUsed = true }, readText: async () => { (window as any).__clipboardUsed = true; return '' } }, configurable: true }) })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('WorkflowCanvas')
      const canvas = page.getByRole('region', { name: '工作流画布' }); await canvas.waitFor()
      const grid = canvas.locator('[data-workflow-action="toggle-grid"]')
      const before = await grid.getAttribute('aria-pressed'); await grid.click()
      expect(await grid.getAttribute('aria-pressed')).not.toBe(before)
      const count = await canvas.locator('.vue-flow__node').count()
      expect(count).toBe(3)
      const node = canvas.locator('[data-id="sample-finish"]')
      const initialUpdates = Number(await page.locator('[data-gallery-canvas-updates]').innerText())
      await node.click()
      expect(Number(await page.locator('[data-gallery-canvas-updates]').innerText())).toBe(initialUpdates)
      const beforeMove = await page.locator('[data-gallery-canvas-position]').innerText()
      const beforeUpdates = Number(await page.locator('[data-gallery-canvas-updates]').innerText())
      const box = (await node.boundingBox())!
      await page.mouse.move(box.x + box.width / 2, box.y + 20); await page.mouse.down()
      await page.mouse.move(box.x + box.width / 2 + 80, box.y + 60, { steps: 8 }); await page.mouse.up()
      await page.waitForFunction((previous) => document.querySelector('[data-gallery-canvas-position]')?.textContent !== previous, beforeMove)
      expect(Number(await page.locator('[data-gallery-canvas-updates]').innerText())).toBeGreaterThan(beforeUpdates)
      await canvas.locator('[data-id="sample-start"]').click()
      await canvas.focus(); await page.keyboard.press('Control+c'); await page.keyboard.press('Control+v')
      await page.waitForFunction((previous) => document.querySelectorAll('.vue-flow__node').length > previous, count)
      expect(await page.evaluate(() => Boolean((window as any).__clipboardUsed))).toBe(false)
      await page.locator('[data-gallery-canvas-locked]').check()
      const lockedCount = await canvas.locator('.vue-flow__node').count()
      await canvas.focus(); await page.keyboard.press('Control+v')
      expect(await canvas.locator('.vue-flow__node').count()).toBe(lockedCount)
      await canvas.locator('[data-id="sample-start"]').dispatchEvent('contextmenu', { bubbles: true, button: 2, clientX: 500, clientY: 400 })
      expect(await page.getByRole('menuitem', { name: '删除', exact: true }).isDisabled()).toBe(true)
      await page.keyboard.press('Escape')
      await page.locator('[data-gallery-canvas-locked]').uncheck()
      await canvas.locator('[data-id="sample-frame"] .wf-canvas-element').dispatchEvent('contextmenu', { bubbles: true, button: 2, clientX: 500, clientY: 400 })
      await page.getByRole('menuitem', { name: '全部删除' }).click()
      const dialog = page.getByRole('dialog', { name: '删除容器及其内容' })
      expect(await dialog.innerText()).toContain('此操作不可撤销')
      expect(await dialog.innerText()).toContain('节点')
      await dialog.getByRole('button', { name: '取消' }).click()
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
