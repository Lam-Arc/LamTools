// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('library name form preview', () => {
  it('shows the real themed dialog and accepts keyboard input', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1100, height: 800 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(20000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('LibraryNameDialog')
      await page.locator('[data-library-name-open]').click()
      const dialog = page.getByRole('dialog', { name: '新建文件夹' })
      const input = dialog.getByLabel('文件夹名称')
      await input.waitFor()
      expect(await input.evaluate(el => document.activeElement === el)).toBe(true)
      const style = await dialog.evaluate(el => ({ width: el.getBoundingClientRect().width, background: getComputedStyle(el).backgroundColor }))
      expect(style.width).toBeGreaterThan(380)
      expect(style.background).not.toBe('rgba(0, 0, 0, 0)')
      await input.fill('示例目录')
      await input.press('Enter')
      expect(await page.locator('[data-library-name-result]').innerText()).toContain('示例目录')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
