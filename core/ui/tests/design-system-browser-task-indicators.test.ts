// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('shared task indicators', () => {
  it('shows the same visible running motion in the plan card and sidebar', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1100, height: 800 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('RuntimeChecklistCard')
      await page.locator('.runtime-checklist-card').click()
      const card = page.locator('.runtime-checklist-card__current .sunday-task-indicator')
      const sidebar = page.locator('.right-sidebar-checklist__step.is-running .sunday-task-indicator')
      expect(await card.count()).toBe(1)
      expect(await sidebar.count()).toBe(1)
      for (const indicator of [card, sidebar]) {
        expect(await indicator.evaluate(el => getComputedStyle(el).animationName)).toBe('sunday-spin')
        expect(await indicator.evaluate(el => getComputedStyle(el).animationDuration)).toBe('1.2s')
        expect(await indicator.evaluate(el => getComputedStyle(el).borderRightColor)).toBe('rgba(0, 0, 0, 0)')
      }
      await page.emulateMedia({ reducedMotion: 'reduce' })
      for (const indicator of [card, sidebar]) expect(await indicator.evaluate(el => getComputedStyle(el).animationName)).toBe('none')
      expect(await sidebar.locator('..').textContent()).toContain('运行中')
      await page.getByLabel('计划状态').click()
      await page.getByRole('button', { name: '失败', exact: true }).click()
      expect(await page.locator('.runtime-checklist-card__current').textContent()).toContain('失败')
      expect(await page.locator('.right-sidebar-checklist__step.is-failed').textContent()).toContain('失败')
      expect(await page.locator('.right-sidebar-checklist__step.is-failed .sunday-spin').count()).toBe(0)
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
