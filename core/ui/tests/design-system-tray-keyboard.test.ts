// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'
// user:“确保视觉、功能和交互不退化”+(托盘开关行可用键盘操作)。
it('toggles tray rows from the keyboard', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage(); page.setDefaultTimeout(30000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('TrayPanel')
    const row = page.getByRole('menuitemcheckbox', { name: /桌宠/ })
    await row.waitFor({ state: 'visible' }); await row.focus()
    expect(await row.evaluate(el => document.activeElement === el)).toBe(true)
    await page.keyboard.press('Enter')
    await page.waitForFunction(() => document.querySelector('[role=menuitemcheckbox]')?.getAttribute('aria-checked') === 'true')
  } finally { await browser.close(); await server.close() }
}, 120000)
