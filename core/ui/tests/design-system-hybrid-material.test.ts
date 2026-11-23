// @vitest-environment node
import { chromium } from 'playwright'
import { expect, it } from 'vitest'
import { createServer } from 'vite'

// user:“尤其是气泡和玻璃效果”+(真实用户与助手气泡共用玻璃材质，角色色不同，关闭助手气泡时保留正文)。
it('compares the shared material on real chat bubbles in both themes', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
  await server.listen()
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1320, height: 960 }, reducedMotion: 'reduce' })
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('MessageView')
    const user = page.locator('[data-ui-instance="message:gallery-user"] .user-bubble')
    const answer = page.locator('[data-ui-instance="message:gallery-assistant"]')
    const assistant = answer.locator('.assistant-bubble--boxed')
    for (const theme of ['深色', '浅色']) {
      if (theme === '浅色') {
        await page.locator('[data-gallery-theme] .ui-select-trigger').click()
        await page.locator('.ui-select-menu .ui-select-option').getByText(theme, { exact: true }).click()
      }
      const material = async (item: typeof user) => item.evaluate(el => {
        // 投影在外壳、模糊与填充在内层 body：取材质要看 body，圆角仍看外壳
        const body = el.querySelector('.message-surface__body') || el
        const styles = getComputedStyle(body)
        const shell = getComputedStyle(el)
        return { background: styles.backgroundColor, filter: styles.backdropFilter, radius: shell.borderTopRightRadius }
      })
      const right = await material(user)
      const left = await material(assistant)
      expect(right.background).not.toBe(left.background)
      expect(right.filter).toContain('blur(')
      expect(right.filter).toBe(left.filter)
      expect(right.radius).toBe(left.radius)
    }
    await page.locator('[data-ui-instance="message:gallery-user"] [data-user-bubble-fold]').click()
    expect(await user.locator('[data-user-bubble-fold]').getAttribute('aria-expanded')).toBe('true')
    await page.getByLabel('助手气泡').uncheck()
    await assistant.waitFor({ state: 'hidden' })
    await answer.getByText('示例回答：任务已经整理完成。').waitFor()

    await page.getByLabel('搜索组件').fill('CoreExecutionControls')
    await page.locator('.core-model-thinking-menu__trigger').click()
    const card = page.locator('.core-model-thinking-menu__glass')
    expect(await card.evaluate(el => getComputedStyle(el).backdropFilter)).toContain('blur(')
    const toggle = page.locator('.core-model-thinking-menu__view-toggle')
    expect(await toggle.evaluate(el => getComputedStyle(el).backdropFilter)).toBe('none')
    await page.locator('.core-model-thinking-menu__group-trigger').click()
    const menu = page.getByRole('listbox', { name: '模型分组' })
    expect(await menu.evaluate(el => getComputedStyle(el).backdropFilter)).toContain('blur(')
    await menu.getByRole('option').first().click()
    await menu.waitFor({ state: 'hidden' })

    const gallery = server.resolvedUrls!.local[0] + 'design-system.html'
    for (const category of ['材质', '基础']) {
      await page.goto(gallery + '?category=' + encodeURIComponent(category))
      const categories = await page.locator('.specimen .category').allTextContents()
      expect(categories.length).toBeGreaterThan(0)
      expect(categories.every(text => text === category)).toBe(true)
    }
  } finally {
    await browser.close()
    await server.close()
  }
}, 30000)
