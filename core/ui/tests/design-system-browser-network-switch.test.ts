// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('network plugin shared switch styles', () => {
  it('works in isolation in light and dark themes with keyboard focus', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ reducedMotion: 'reduce' })
      page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.evaluate(() => document.querySelectorAll('style, link[rel=stylesheet]').forEach(el => el.remove()))
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/network-switch.ts' })
      const input = page.getByRole('switch', { name: '网络开关示例' })
      await input.waitFor()
      await page.keyboard.press('Tab')
      expect(await input.evaluate(el => el.matches(':focus-visible'))).toBe(true)
      expect(await page.locator('#network-switch-fixture .sunday-switch__track').evaluate(el => getComputedStyle(el).outlineStyle)).toBe('solid')
      const select = page.getByRole('button', { name: '网络下拉示例' })
      expect(await select.evaluate(el => getComputedStyle(el).height)).toBe('32px')
      await select.click()
      await page.locator('.ui-select-menu .ui-select-option').getByText('第二项', { exact: true }).click()
      expect(await select.innerText()).toContain('第二项')
      for (const theme of ['dark', 'light']) {
        await page.locator('#network-switch-fixture').evaluate((el, theme) => {
          const dark = theme === 'dark'
          el.style.setProperty('--theme-control-solid', dark ? '#ffffff' : '#1f1f1f')
          el.style.setProperty('--theme-control-text', dark ? '#1f1f1f' : '#ffffff')
          el.style.setProperty('--theme-main-text', dark ? '#ffffff' : '#1f1f1f')
        }, theme)
        await input.check()
        const colors = await page.locator('#network-switch-fixture .sunday-switch__track').evaluate(el => ({ track: getComputedStyle(el).backgroundColor, thumb: getComputedStyle(el.querySelector('.sunday-switch__thumb')!).backgroundColor, width: getComputedStyle(el).width }))
        expect(colors.width).toBe('40px')
        expect(colors.track).not.toBe(colors.thumb)
        await input.uncheck()
      }
    } finally { await browser.close(); await server.close() }
  }, 30000)
})
