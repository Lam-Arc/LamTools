// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('pet settings gallery isolation', () => {
  it('lets the user edit a local sample without calling desktop services', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
      await page.addInitScript(() => {
        const state = globalThis as any
        state.__petPreviewCalls = []
        state.__TAURI_INTERNALS__ = { invoke: async (...args: unknown[]) => { state.__petPreviewCalls.push(args); return null }, transformCallback: () => 1, unregisterCallback: () => {} }
      })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CorePetEditor')
      const editor = page.locator('.pet-settings-editor')
      const card = editor.locator('.setting-card').first()
      expect(await card.evaluate(el => getComputedStyle(el).borderStyle)).toBe('solid')
      expect(await card.evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)')
      const sector = editor.locator('.pet-settings-sector-label').first()
      await sector.fill('预览示例'); await sector.blur()
      expect(await sector.inputValue()).toBe('预览示例')
      const check = editor.locator('.pet-settings-row').filter({ hasText: '启用桌宠' }).locator('input')
      await check.setChecked(!(await check.isChecked()))
      expect(await page.evaluate(() => (globalThis as any).__petPreviewCalls)).toEqual([])
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
