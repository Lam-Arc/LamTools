// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('project creation gallery isolation', () => {
  it('uses local directory data and never invokes the native picker', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
      await page.addInitScript(() => { (window as any).__pickerCalls = 0; (window as any).__LAMTOOLS_PICK_DIRECTORY = async () => { (window as any).__pickerCalls++; return 'E:/real' } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreProjectCreate')
      await page.locator('[data-project-create-preview-open]').click()
      const project = page.getByRole('dialog', { name: '新建项目' })
      await project.locator('[data-project-browse]').click()
      const directory = page.getByRole('dialog', { name: '选择目录' })
      await directory.waitFor()
      expect(await page.evaluate(() => (window as any).__pickerCalls)).toBe(0)
      await page.keyboard.press('Escape')
      await directory.waitFor({ state: 'hidden' })
      await project.locator('[data-project-root]').fill('E:/sample')
      await project.locator('[data-project-name]').fill('示例')
      await project.locator('[data-project-submit]').click()
      expect(await page.locator('[data-project-create-preview-result]').innerText()).toContain('示例')
      expect(await page.evaluate(() => (window as any).__pickerCalls)).toBe(0)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
