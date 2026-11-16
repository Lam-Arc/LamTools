// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
describe('built network plugin', () => {
  it('loads its own styles and switches a real node through its public entry', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1000, height: 800 } })
      page.setDefaultTimeout(8000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.evaluate(() => document.querySelectorAll('style, link[rel=stylesheet]').forEach(node => node.remove()))
      await page.addScriptTag({ type: 'module', url: server.resolvedUrls!.local[0] + 'tests/fixtures/design-system/network-built.ts' })
      const trigger = page.locator('#network-built-fixture [data-network-quick-node] button')
      await trigger.waitFor({ state: 'visible' })
      await trigger.click()
      await page.locator('.ui-select-menu .ui-select-option').getByText('Singapore', { exact: true }).click()
      expect(await page.locator('#network-built-result').innerText()).toContain('"name":"Singapore"')
      expect(await trigger.evaluate(el => getComputedStyle(el).height)).toBe('32px')
      const primary = page.locator('#network-built-main .btn--primary').first()
      await primary.waitFor({ state: 'visible' })
      await page.addStyleTag({ content: '*, *::before, *::after { transition: none !important; animation: none !important; }' })
      for (const [surface, ink] of [['#ffffff', '#151515'], ['#151515', '#ffffff']]) {
        await page.locator('#network-built-main').evaluate((element, colors) => {
          (element as HTMLElement).style.setProperty('--theme-control-solid', colors[0])
          ;(element as HTMLElement).style.setProperty('--theme-control-text', colors[1])
        }, [surface, ink])
        const pair = await primary.evaluate(element => ({ background: getComputedStyle(element).backgroundColor, text: getComputedStyle(element).color }))
        expect(pair.background).toBe(surface === '#ffffff' ? 'rgb(255, 255, 255)' : 'rgb(21, 21, 21)')
        expect(pair.text).toBe(ink === '#ffffff' ? 'rgb(255, 255, 255)' : 'rgb(21, 21, 21)')
      }

    } finally { await browser.close(); await server.close() }
  }, 30000)
})
