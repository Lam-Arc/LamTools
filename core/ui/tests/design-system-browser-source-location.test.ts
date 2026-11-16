// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“源码定位”“让后续开发及 Agent 能快速检索”+(按完整源码路径查找并复制项目相对路径)。
describe('gallery source location', () => {
  it('finds and copies component and bundled plugin paths', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(30000); page.setDefaultNavigationTimeout(30000)
      await page.addInitScript(() => { Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (text: string) => { (window as any).__copied = text } }, configurable: true }) })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      const search = page.getByLabel('搜索组件')
      for (const [name, path] of [
        ['CoreSplitPreview', 'core/ui/src/components/CoreSplitPreview.vue'],
        ['WorkflowCanvas', 'core/src/lamtools_core/plugins/bundled/workflow/ui/WorkflowCanvas.vue'],
      ]) {
        await search.fill(path)
        const item = page.locator('.specimen').filter({ has: page.getByRole('heading', { name, exact: true }) })
        await item.getByRole('button', { name: '复制源码路径' }).click()
        expect(await page.evaluate(() => (window as any).__copied)).toBe(path)
        expect(await item.innerText()).toContain('路径已复制')
      }
      await page.evaluate(() => { Object.defineProperty(navigator, 'clipboard', { value: { writeText: async () => { throw new Error('denied') } }, configurable: true }); document.execCommand = () => false })
      const workflow = page.locator('.specimen').filter({ has: page.getByRole('heading', { name: 'WorkflowCanvas', exact: true }) })
      await workflow.getByRole('button', { name: '复制源码路径' }).click()
      expect(await workflow.getByText('复制失败，请手动选择路径').count()).toBe(1)
      await page.evaluate(() => { Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (text: string) => { (window as any).__copied = text } }, configurable: true }) })
      const includedPath = 'core/ui/src/components/CommandPalette.vue'
      await search.fill(includedPath)
      const included = page.locator('.specimen').filter({ has: page.getByRole('heading', { name: 'InlineFileComposer', exact: true }) })
      await included.locator('[data-source-path]').filter({ hasText: includedPath }).getByRole('button', { name: '复制源码路径' }).click()
      expect(await page.evaluate(() => (window as any).__copied)).toBe(includedPath)
      const pendingPath = 'core/ui/src/components/CoreSplitBrowser.vue'
      await search.fill(pendingPath)
      await page.locator('[data-show-inventory]').click()
      const row = page.locator(`[data-inventory-path="${pendingPath}"]`)
      await row.getByRole('button', { name: '复制路径' }).click()
      expect(await page.evaluate(() => (window as any).__copied)).toBe(pendingPath)
      expect(await row.innerText()).toContain('路径已复制')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
