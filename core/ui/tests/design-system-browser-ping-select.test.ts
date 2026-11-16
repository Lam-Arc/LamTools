// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('Ping shared select rendering', () => {
  it('opens the preview menu above the editor and applies a choice', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/ping.ts' })
      const capture = page.locator('#ping-fixture .ping-capture-sandbox .capture')
      const box = await capture.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.height).toBeLessThan(800)
      const canvas = page.locator('#ping-fixture .ping-capture-sandbox canvas.capture__canvas')
      await canvas.scrollIntoViewIfNeeded()
      const canvasBox = await canvas.boundingBox()
      await page.mouse.move(canvasBox!.x + 40, canvasBox!.y + 40)
      await page.mouse.down()
      await page.mouse.move(canvasBox!.x + 140, canvasBox!.y + 140)
      await page.mouse.up()
      expect(await capture.locator('.capture__hint').count()).toBe(0)
      await capture.getByRole('button', { name: '发送', exact: true }).click()
      const result = await page.locator('#ping-fixture .ping-capture-sandbox__result').innerText()
      const dimensions = result.match(/成功：([\d.]+)×([\d.]+)/)
      expect(dimensions).not.toBeNull()
      expect(Number(dimensions![1])).toBeCloseTo(100 * 1200 / canvasBox!.width, 0)
      expect(Number(dimensions![2])).toBeCloseTo(100 * 1200 / canvasBox!.width, 0)
      const size = page.locator('#ping-fixture [data-ping-preview-size] button')
      await size.click()
      await page.locator('.ui-select-menu .ui-select-option').getByText('方形 · 1200×1200', { exact: true }).click()
      expect(await size.innerText()).toContain('方形')
    } finally { await browser.close(); await server.close() }
  }, 30000)
  it('keeps the standalone capture editor full-screen', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1000, height: 700 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/capture.ts' })
      const box = await page.locator('#capture-fixture .capture').boundingBox()
      expect(box).toMatchObject({ x: 0, y: 0, width: 1000, height: 700 })
    } finally { await browser.close(); await server.close() }
  }, 30000)

})
