// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('project modal keyboard flow', () => {
  it('keeps focus inside project and nested directory dialogs and restores it after cancellation', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
      page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/project-modal.ts' })
      const pickerOpener = page.locator('#open-project-picker')
      await pickerOpener.click()
      const picker = page.getByRole('dialog', { name: '选择项目' })
      await picker.waitFor()
      expect(await picker.evaluate(el => el.contains(document.activeElement))).toBe(true)
      for (let n = 0; n < 5; n++) { await page.keyboard.press('Tab'); expect(await picker.evaluate(el => el.contains(document.activeElement))).toBe(true) }
      await page.keyboard.press('Escape')
      await picker.waitFor({ state: 'hidden' })
      expect(await pickerOpener.evaluate(el => document.activeElement === el)).toBe(true)
      const createOpener = page.locator('#open-project-create')
      await createOpener.click()
      const create = page.getByRole('dialog', { name: '新建项目' })
      await create.waitFor()
      for (let n = 0; n < 8; n++) { await page.keyboard.press('Tab'); expect(await create.evaluate(el => el.contains(document.activeElement))).toBe(true) }
      await create.locator('[data-project-browse]').click()
      const directory = page.getByRole('dialog', { name: '选择目录' })
      await directory.waitFor()
      await directory.focus()
      await page.keyboard.press('Shift+Tab')
      expect(await directory.evaluate(el => el.contains(document.activeElement))).toBe(true)
      await page.keyboard.press('Escape')
      await directory.waitFor({ state: 'hidden' })
      expect(await create.isVisible()).toBe(true)
      expect(await create.locator('[data-project-browse]').evaluate(el => document.activeElement === el)).toBe(true)
      await page.keyboard.press('Escape')
      await create.waitFor({ state: 'hidden' })
      expect(await createOpener.evaluate(el => document.activeElement === el)).toBe(true)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
