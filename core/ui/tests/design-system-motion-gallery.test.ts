// @vitest-environment node
import { chromium } from 'playwright'
import { expect, it } from 'vitest'
import { createServer } from 'vite'

// user:“做”+(一个入口比较真实菜单、入场与等待，系统减少动效时保留功能和状态)。
it('previews shared motion and keeps controls usable with reduced motion', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
  await server.listen()
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ reducedMotion: 'no-preference' })
    page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html?category=' + encodeURIComponent('动效'))
    const demo = page.locator('[data-motion-preview]')
    await demo.getByRole('button', { name: '重播入场' }).click()
    const animation = (selector: string) => page.locator(selector).first().evaluate(el => getComputedStyle(el).animationName)
    expect(await animation('[data-motion-row]')).toBe('stream-enter')
    expect(await animation('[data-motion-spinner]')).toBe('sunday-spin')
    const trigger = demo.getByRole('button', { name: '示例浮层' })
    await trigger.click()
    expect(await animation('.ui-select-menu.sunday-motion-popover')).toBe('popover-in')
    await page.keyboard.press('Escape')
    await page.locator('.ui-select-menu.sunday-motion-popover').waitFor({ state: 'hidden' })

    await demo.getByLabel('模拟减少动效').check()
    expect(await animation('[data-motion-row]')).toBe('none')
    expect(await animation('[data-motion-spinner]')).toBe('none')
    await trigger.click()
    expect(await animation('.ui-select-menu.sunday-motion-popover')).toBe('none')
    await page.locator('.ui-select-menu').getByRole('button', { name: '第二项' }).click()
    expect(await trigger.innerText()).toBe('第二项')
    await demo.getByLabel('模拟减少动效').uncheck()
    await page.emulateMedia({ reducedMotion: 'reduce' })
    expect(await animation('[data-motion-spinner]')).toBe('none')

    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.getByRole('button', { name: '打开示例菜单' }).click()
    const menuContent = page.locator('[data-context-menu-level="0"] .context-menu-panel-content.sunday-motion-popover')
    expect(await menuContent.evaluate(el => getComputedStyle(el).animationName)).toBe('popover-in')
    await page.getByRole('heading', { name: '组件展厅', exact: true }).click()
    await menuContent.waitFor({ state: 'detached' })
  } finally {
    await browser.close()
    await server.close()
  }
}, 30000)
