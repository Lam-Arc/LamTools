// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(画布连线删除和拖动创建均同步到工作流)。
describe('workflow canvas connections', () => {
  it('removes and reconnects the real nodes in the preview', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('WorkflowCanvas')
      const canvas = page.getByRole('region', { name: '工作流画布' }); await canvas.waitFor()
      const edge = canvas.locator('.vue-flow__edge').first(); await edge.waitFor()
      await edge.dispatchEvent('contextmenu', { bubbles: true, button: 2, clientX: 500, clientY: 400 })
      await page.getByRole('menuitem', { name: '删除连线' }).click()
      await page.waitForFunction(() => document.querySelector('[data-gallery-canvas-edges]')?.textContent === '0')
      const source = canvas.locator('[data-id="sample-start"] .vue-flow__handle.source')
      const target = canvas.locator('[data-id="sample-finish"] .vue-flow__handle.target')
      const a = (await source.boundingBox())!; const b = (await target.boundingBox())!
      await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2); await page.mouse.down()
      await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 20 }); await page.mouse.up()
      await page.waitForFunction(() => document.querySelector('[data-gallery-canvas-edges]')?.textContent === '1')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
