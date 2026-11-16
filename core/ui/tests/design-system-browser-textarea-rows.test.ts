// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('automatic textarea row limit', () => {
  it('keeps five full lines visible before scrolling and responds to a smaller minimum', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('AutoTextarea')
      const textarea = page.getByLabel('文本示例')
      await textarea.fill('一\n二\n三\n四\n五')
      const metrics = await textarea.evaluate(el => {
        const style = getComputedStyle(el)
        return { visible: el.clientHeight, scroll: el.scrollHeight, line: parseFloat(style.lineHeight), padding: parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) }
      })
      expect(metrics.visible).toBeGreaterThanOrEqual(Math.floor(metrics.line * 5 + metrics.padding) - 1)
      expect(metrics.scroll - metrics.visible).toBeLessThanOrEqual(1)
      await textarea.fill('一\n二\n三\n四\n五\n六')
      expect(await textarea.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true)
      await page.getByLabel('最少行数').fill('1')
      await page.getByLabel('最多行数').fill('3')
      await textarea.fill('一\n二\n三')
      expect(await textarea.evaluate(el => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(1)
      await textarea.fill('一\n二\n三\n四')
      expect(await textarea.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true)
    } finally { await browser.close(); await server.close() }
  }, 60000)
  it('recalculates height when its width changes and text wraps', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('AutoTextarea')
      const textarea = page.getByLabel('文本示例')
      await textarea.evaluate((el: HTMLTextAreaElement) => { el.style.width = '400px' })
      await textarea.fill('这是一段用于检查输入框宽度变化后自动换行高度的示例文字。')
      const initialHeight = await textarea.evaluate(el => el.clientHeight)
      await textarea.evaluate((el: HTMLTextAreaElement) => { el.style.width = '120px' })
      await page.waitForFunction(({ height }) => (document.querySelector('[aria-label="文本示例"]') as HTMLElement)?.clientHeight > height, { height: initialHeight }, { timeout: 3000 })
      expect(await textarea.evaluate(el => el.scrollHeight - el.clientHeight)).toBeLessThanOrEqual(1)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
