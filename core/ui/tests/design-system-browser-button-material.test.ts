// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('shared primary material', () => {
  it('supports the control image and glass tokens without losing the control text', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('SundayButton')
      const button = page.locator('.preview .btn--primary')
      const result = await button.evaluate(element => {
        element.classList.add('btn--material')
        const root = element.parentElement as HTMLElement
        root.style.setProperty('--theme-control-image', 'linear-gradient(rgb(20, 20, 20), rgb(30, 30, 30))')
        root.style.setProperty('--theme-control-image-size', 'cover')
        root.style.setProperty('--theme-control-image-repeat', 'no-repeat')
        root.style.setProperty('--theme-control-glass-filter', 'blur(4px)')
        root.style.setProperty('--theme-control-text', '#ffffff')
        const style = getComputedStyle(element)
        return { image: style.backgroundImage, size: style.backgroundSize, repeat: style.backgroundRepeat, filter: style.backdropFilter, text: style.color }
      })
      expect(result.image).toContain('linear-gradient')
      expect(result.size).toBe('cover')
      expect(result.repeat).toBe('no-repeat')
      expect(result.filter).toBe('blur(4px)')
      expect(result.text).toBe('rgb(255, 255, 255)')
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
