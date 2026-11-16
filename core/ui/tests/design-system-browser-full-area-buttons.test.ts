// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('full-area buttons', () => {
  it('preserves themed primary buttons and page navigation in both pages', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click()
        await page.getByRole('button', { name: theme, exact: true }).click()
        const styles = []
        for (const [component, root] of [['CoreSuperAgentPanel', '.sa-view'], ['CoreArrangeManager', '.arrange-view']]) {
          await page.getByLabel('搜索组件').fill(component)
          const primary = page.locator(`${root} .primary-button`).first()
          await primary.waitFor()
          styles.push(await primary.evaluate(el => { const s = getComputedStyle(el); return { background: s.backgroundColor, color: s.color, radius: s.borderRadius, padding: s.padding } }))
          await page.emulateMedia({ reducedMotion: 'reduce' })
          expect(await primary.evaluate(el => getComputedStyle(el).transitionDuration)).toBe('0s')
          await page.emulateMedia({ reducedMotion: 'no-preference' })
          await primary.click()
          expect(await page.locator(`${root} textarea`).count()).toBeGreaterThan(0)
        }
        expect(styles[0]).toEqual(styles[1])
        expect(styles[0].radius).toBe('6px')
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
