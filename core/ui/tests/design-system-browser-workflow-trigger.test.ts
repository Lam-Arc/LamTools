// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('workflow trigger preview in a browser', () => {
  it('renders the shared action legibly in both control themes and saves a local draft', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('WorkflowTriggersPanel')
      const save = page.locator('[data-trigger-save]')
      for (const [fill, text] of [['rgb(250, 247, 240)', 'rgb(40, 40, 40)'], ['rgb(40, 40, 40)', 'rgb(250, 247, 240)']]) {
        const style = await save.evaluate((element, colors) => {
          const panel = element as HTMLElement
          panel.style.transition = 'none'
          panel.style.setProperty('--theme-control-solid', colors[0])
          panel.style.setProperty('--theme-control-text', colors[1])
          panel.style.setProperty('--settings-control-solid', colors[0])
          panel.style.setProperty('--settings-control-text', colors[1])
          const computed = getComputedStyle(element)
          return { background: computed.backgroundColor, color: computed.color, height: element.getBoundingClientRect().height }
        }, [fill, text])
        expect(style.background).toBe(fill)
        expect(style.color).toBe(text)
        expect(style.height).toBe(28)
      }
      await page.locator('.wf-trigger-panel input.sunday-checkbox').uncheck()
      await save.click()
      await expect(page.locator('[data-trigger-gallery-result]').textContent()).resolves.toContain('已保存')
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
