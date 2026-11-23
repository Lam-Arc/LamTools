// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件，支持分类、搜索、筛选、实时预览、交互测试”+(灯箱用本地内容验证打开、关闭和焦点)。
describe('preview lightbox gallery', () => {
  it('opens the real lightbox and restores focus on Escape', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('PreviewLightbox')
      const open = page.getByRole('button', { name: '打开示例预览' })
      await open.click()
      const dialog = page.getByRole('dialog', { name: '预览：示例文档' })
      await dialog.waitFor()
      await expect.poll(() => dialog.evaluate(el => document.activeElement === el)).toBe(true)
      expect(await dialog.locator('iframe').getAttribute('sandbox')).toBe('')
      expect(await dialog.locator('iframe').getAttribute('srcdoc')).toContain('展厅示例内容')
      await page.keyboard.press('Escape')
      await expect.poll(() => open.evaluate(el => document.activeElement === el)).toBe(true)
      expect(await dialog.count()).toBe(0)
      expect(await page.locator('[data-source-path="core/ui/src/preview/PreviewSurface.vue"]').count()).toBe(1)
      await page.getByLabel('预览主题').click()
      await page.getByRole('button', { name: '浅色', exact: true }).click()
      await open.click()
      await dialog.waitFor()
      const lightBackground = await dialog.evaluate(el => getComputedStyle(el).backgroundColor)
      await page.locator('[data-preview-lightbox]').click({ position: { x: 2, y: 2 } })
      await expect.poll(() => open.evaluate(el => document.activeElement === el)).toBe(true)
      await page.getByLabel('预览主题').click()
      await page.getByRole('button', { name: '深色', exact: true }).click()
      await open.click(); await dialog.waitFor()
      expect(await dialog.evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe(lightBackground)
    } finally { await browser.close(); await server.close() }
  }, 120000)
})
