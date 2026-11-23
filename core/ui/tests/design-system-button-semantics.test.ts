// @vitest-environment node
import { chromium } from 'playwright'
import { expect, it } from 'vitest'
import { createServer } from 'vite'

// user:“按钮是否包含主输入栏内的发送/暂停/停止按钮？UI 请按语义整理并展示”+(用真实按键短按暂停、长按终止，终止前保留确认)。
it('shows the composer action lifecycle and confirms long-press termination', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
  await server.listen()
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ reducedMotion: 'reduce' })
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html', { waitUntil: 'domcontentloaded' })
    const search = page.getByLabel('搜索组件')
    await search.fill('会话控制')
    const composer = page.locator('[data-composer-actions]')
    const button = composer.locator('.core-send-stop-button')
    await button.click()
    expect(await button.getAttribute('aria-label')).toBe('停止运行')
    await button.click()
    expect(await button.getAttribute('aria-label')).toBe('继续运行')
    await button.click()
    expect(await button.getAttribute('aria-label')).toBe('停止运行')
    const bounds = (await button.boundingBox())!
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
    await page.mouse.down()
    const dialog = page.getByRole('dialog', { name: '终止这个回合？' })
    await dialog.waitFor({ timeout: 3000 })
    await page.mouse.up()
    await dialog.getByRole('button', { name: '终止' }).click()
    await composer.getByRole('status').getByText('示例操作：已终止回合').waitFor()
    expect(await button.getAttribute('aria-label')).toBe('发送')
  } finally {
    await browser.close()
    await server.close()
  }
}, 30000)
