// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('workflow trigger keyboard focus', () => {
  it('shows focus on the trigger type selector and supports keyboard choice', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage()
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('WorkflowTriggersPanel')
      const select = page.locator('.wf-trigger-panel .ui-select-trigger').first()
      await select.focus()
      const focus = await select.evaluate(el => ({ style: getComputedStyle(el).outlineStyle, width: getComputedStyle(el).outlineWidth }))
      expect(focus.style).toBe('solid')
      expect(focus.width).toBe('2px')
      await select.press('Enter')
      await page.keyboard.press('ArrowDown')
      await page.keyboard.press('Enter')
      expect(await select.getAttribute('aria-expanded')).toBe('false')
      await expect(select.textContent()).resolves.not.toContain('手动')
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
