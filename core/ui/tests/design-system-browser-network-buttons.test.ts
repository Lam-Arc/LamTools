// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('network button theme integration', () => {
  it('uses shared control colors and keeps primary and secondary actions legible in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/network-buttons.ts' })
      await page.addStyleTag({ content: '*, *::before, *::after { transition: none !important; animation: none !important; }' })
      for (const theme of ['dark', 'light']) {
        const result = await page.locator('#network-buttons-fixture').evaluate((root, theme) => {
          const dark = theme === 'dark'
          const el = root as HTMLElement
          el.style.setProperty('--theme-main-background', dark ? '#151515' : '#ffffff')
          el.style.setProperty('--theme-main-text', dark ? '#f5f5f5' : '#151515')
          el.style.setProperty('--theme-control-solid', dark ? '#ffffff' : '#151515')
          el.style.setProperty('--theme-control-text', dark ? '#151515' : '#ffffff')
          const primary = root.querySelector<HTMLElement>('[data-network-primary]')!
          const secondary = root.querySelector<HTMLElement>('[data-network-secondary]')!
          return { settings: getComputedStyle(primary).getPropertyValue('--settings-control-solid'), theme: getComputedStyle(primary).getPropertyValue('--theme-control-solid'), primaryBg: getComputedStyle(primary).backgroundColor, primaryText: getComputedStyle(primary).color, secondaryBg: getComputedStyle(secondary).backgroundColor, secondaryText: getComputedStyle(secondary).color }
        }, theme)
        expect(result.primaryBg, JSON.stringify(result)).toBe(theme === 'dark' ? 'rgb(255, 255, 255)' : 'rgb(21, 21, 21)')
        expect(result.primaryText).toBe(theme === 'dark' ? 'rgb(21, 21, 21)' : 'rgb(255, 255, 255)')
        expect(result.secondaryBg).not.toBe(result.primaryBg)
        expect(result.secondaryText).toBe(theme === 'dark' ? 'rgb(245, 245, 245)' : 'rgb(21, 21, 21)')
      }
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
