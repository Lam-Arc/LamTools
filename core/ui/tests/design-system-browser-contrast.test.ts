// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

describe('rendered shared controls', () => {
  it('keeps the checked indicator legible in both actual application themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0, strictPort: false } })
    await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1200, height: 850 } })
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      const stableStyles = await page.addStyleTag({ content: '*, *::before, *::after { transition: none !important; animation: none !important; }' })
      const setTheme = async (theme: string) => {
        await page.locator('[data-gallery-theme] .ui-select-trigger').click()
        await page.locator('.ui-select-menu .ui-select-option').getByText(theme === 'light' ? '浅色' : '深色', { exact: true }).click()
      }
      // user:“源码定位”+(展厅必须展示真实共享样式，而不是只有组件模板)。
      await page.getByLabel('搜索组件').fill('SundaySwitch')
      await page.locator('[data-source="SundaySwitch"]').click()
      expect(await page.locator('[data-source-content="SundaySwitch"]').textContent()).toContain('.sunday-switch__track')
      await page.getByLabel('搜索组件').fill('UiSelect')
      await page.locator('[data-source="UiSelect"]').click()
      expect(await page.locator('[data-source-content="UiSelect"]').textContent()).toContain('.ui-select-trigger')
      await page.getByLabel('搜索组件').fill('SundayCheckbox')
      const check = page.getByLabel('示例复选框')
      const normal = await check.evaluate(element => getComputedStyle(element).backgroundColor)
      await check.hover()
      const hover = await check.evaluate(element => getComputedStyle(element).backgroundColor)
      await page.mouse.down()
      const pressed = await check.evaluate(element => getComputedStyle(element).backgroundColor)
      await page.mouse.up()
      expect(hover).not.toBe(normal)
      expect(pressed).not.toBe(hover)
      await check.check()
      for (const theme of ['dark', 'light']) {
        await setTheme(theme)
        const colors = await check.evaluate(element => ({ background: getComputedStyle(element).backgroundColor, mark: getComputedStyle(element, '::after').borderLeftColor }))
        const rgb = (color: string) => (color.match(/[\d.]+/g) || []).slice(0, 3).map(Number)
        const luminance = (values: number[]) => values.map(value => value / 255).map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0)
        const [a, b] = [luminance(rgb(colors.background)), luminance(rgb(colors.mark))].sort((x, y) => y - x)
        expect((a + 0.05) / (b + 0.05), `${theme}: ${JSON.stringify(colors)}`).toBeGreaterThanOrEqual(3)
      }
      // Primary and secondary actions must stay distinguishable in both theme presets.
      await page.getByLabel('搜索组件').fill('SundayButton')
      await page.locator('[data-source="SundayButton"]').click()
      expect(await page.locator('[data-source-content="SundayButton"]').textContent()).toContain('.btn--primary')
      for (const theme of ['dark', 'light']) {
        await setTheme(theme)
        const pair = await page.locator('.preview').evaluate(root => {
          const primary = root.querySelector<HTMLElement>('.btn--primary')!
          const secondary = root.querySelector<HTMLElement>('.btn--secondary')!
          const probe = document.createElement('span')
          probe.style.color = 'var(--theme-control-text)'
          root.appendChild(probe)
          const result = { primaryBackground: getComputedStyle(primary).backgroundColor, secondaryBackground: getComputedStyle(secondary).backgroundColor, settings: getComputedStyle(primary).getPropertyValue('--settings-control-text'), theme: getComputedStyle(primary).getPropertyValue('--theme-control-text'), primaryText: getComputedStyle(primary).color, expectedText: getComputedStyle(probe).color }
          probe.remove()
          return result
        })
        expect(pair.primaryBackground, theme).not.toBe(pair.secondaryBackground)
        expect(pair.primaryText, `${theme}: ${JSON.stringify(pair)}`).toBe(pair.expectedText)
        const rgb = (color: string) => (color.match(/[\d.]+/g) || []).slice(0, 3).map(Number)
        const luminance = (values: number[]) => values.map(value => value / 255).map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0)
        const [a, b] = [luminance(rgb(pair.primaryBackground)), luminance(rgb(pair.primaryText))].sort((x, y) => y - x)
        expect((a + 0.05) / (b + 0.05), theme).toBeGreaterThanOrEqual(4.5)
        const ratios = await page.locator('.preview').evaluate(root => {
          const canvas = document.createElement('canvas')
          canvas.width = 1; canvas.height = 1
          const context = canvas.getContext('2d')!
          const luminance = (rgb: Uint8ClampedArray) => [...rgb].slice(0, 3).map(value => value / 255).map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0)
          const result: Record<string, number> = {}
          for (const button of root.querySelectorAll<HTMLElement>('.btn')) {
            context.clearRect(0, 0, 1, 1)
            context.fillStyle = getComputedStyle(root).backgroundColor
            context.fillRect(0, 0, 1, 1)
            context.fillStyle = getComputedStyle(button).backgroundColor
            context.fillRect(0, 0, 1, 1)
            const background = luminance(context.getImageData(0, 0, 1, 1).data)
            context.fillStyle = getComputedStyle(button).color
            context.fillRect(0, 0, 1, 1)
            const text = luminance(context.getImageData(0, 0, 1, 1).data)
            result[button.textContent || ''] = (Math.max(background, text) + 0.05) / (Math.min(background, text) + 0.05)
          }
          return result
        })
        for (const [variant, ratio] of Object.entries(ratios)) expect(ratio, `${theme} ${variant}`).toBeGreaterThanOrEqual(4.5)
      }
      const fallback = await page.locator('.preview').evaluate(root => {
        const element = root as HTMLElement
        for (const name of ['--theme-control-solid', '--theme-control-text', '--theme-main-text']) element.style.setProperty(name, 'initial')
        const primary = root.querySelector<HTMLElement>('.btn--primary')!
        return { background: getComputedStyle(primary).backgroundColor, text: getComputedStyle(primary).color }
      })
      expect(fallback).toEqual({ background: 'rgb(251, 247, 240)', text: 'rgb(46, 49, 56)' })
      const scoped = await page.locator('.preview').evaluate(root => {
        const element = root as HTMLElement
        element.style.setProperty('--settings-control-solid', '#ffffff')
        element.style.setProperty('--settings-control-text', '#111111')
        element.style.setProperty('--settings-main-text', '#abcdef')
        const primary = root.querySelector<HTMLElement>('.btn--primary')!
        const secondary = root.querySelector<HTMLElement>('.btn--secondary')!
        return { background: getComputedStyle(primary).backgroundColor, text: getComputedStyle(primary).color, secondaryText: getComputedStyle(secondary).color }
      })
      expect(scoped).toEqual({ background: 'rgb(255, 255, 255)', text: 'rgb(17, 17, 17)', secondaryText: 'rgb(171, 205, 239)' })
      await stableStyles.evaluate(element => element.remove())
      await page.emulateMedia({ reducedMotion: 'reduce' })
      const durations = await page.locator('.preview .btn--primary').evaluate(element => getComputedStyle(element).transitionDuration)
      expect(durations.split(',').every(value => Number.parseFloat(value) === 0)).toBe(true)
      await page.getByLabel('搜索组件').fill('UiSelect')
      await page.locator('[data-select-preview]').evaluate(element => {
        const next = document.createElement('button')
        next.dataset.nextControl = ''
        next.textContent = '下一个控件'
        element.after(next)
      })
      await page.locator('.preview').evaluate(element => (element as HTMLElement).style.setProperty('--ui-select-layer', 'var(--z-fullscreen, 900)'))
      await page.getByLabel('示例选项').click()
      expect(await page.locator('.ui-select-menu').evaluate(element => getComputedStyle(element).zIndex)).toBe('900')
      await page.locator('.ui-select-option').first().press('Tab')
      await expect.poll(() => page.locator('[data-next-control]').evaluate(element => element === document.activeElement)).toBe(true)
      expect(await page.getByLabel('示例选项').getAttribute('aria-expanded')).toBe('false')
      await page.close()
    } finally {
      await browser.close()
      await server.close()
    }
  })
})
