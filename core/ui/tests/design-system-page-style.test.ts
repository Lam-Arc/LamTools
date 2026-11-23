// @vitest-environment node
import { chromium } from 'playwright'
import { expect, it } from 'vitest'
import { createServer } from 'vite'

// user:“我不是说展厅要重做，而是这个组内的 UI 设计与风格”+(验证的是生产页面渲染出的通用布局与操作)。
it('uses the same page styles across the real call console, settings and connection views', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
  await server.listen()
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1390, height: 900 } })
    page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    const search = page.getByLabel('搜索组件')
    const style = (selector: string, property: string) => page.locator(selector).first().evaluate(
      (element, key) => getComputedStyle(element).getPropertyValue(key), property,
    )

    await search.fill('DirectCallView')
    const titleSize = await style('.dc-head .sunday-page-title', 'font-size')
    const panelRadius = await style('.dc-compose.sunday-page-panel', 'border-radius')
    const darkPanel = await style('.dc-compose.sunday-page-panel', 'background-color')
    await page.locator('[data-gallery-theme] .ui-select-trigger').click()
    await page.locator('.ui-select-menu').getByRole('button', { name: '浅色', exact: true }).click()
    expect(await style('.dc-compose.sunday-page-panel', 'background-color')).not.toBe(darkPanel)

    await search.fill('CoreProjectSettings')
    expect(await style('.settings-title h1', 'font-size')).toBe(titleSize)
    const sections = page.locator('.sunday-project-sheet > .setting-card')
    expect(await sections.count()).toBeGreaterThan(1)
    expect(await sections.first().evaluate(el => getComputedStyle(el).backgroundColor)).toBe('rgba(0, 0, 0, 0)')

    await search.fill('AccountShell')
    expect(await style('.device-page__head .sunday-page-title', 'font-size')).toBe(titleSize)
    expect(await style('.transfer-panel.sunday-page-panel', 'border-radius')).toBe(panelRadius)
    await page.getByRole('button', { name: '生成配对二维码' }).click()
    await page.locator('.pair-card.sunday-page-panel').waitFor()

    await search.fill('SearchShell')
    const searchTabs = page.locator('.search-tabs.sunday-page-tabs')
    await searchTabs.getByRole('button').nth(1).click()
    expect(await searchTabs.getByRole('button').nth(1).getAttribute('aria-current')).toBe('page')
    const searchActive = await searchTabs.getByRole('button').nth(1).evaluate(el => getComputedStyle(el).backgroundColor)
    await search.fill('CoreArrangeManager')
    const taskActive = await style('.filter-tabs.sunday-page-tabs .active', 'background-color')
    expect(taskActive).toBe(searchActive)

    await search.fill('InlineFileComposer')
    const composer = page.locator('.composer-root--embedded')
    const field = composer.locator('.cm-content')
    const outline = () => composer.locator('.floating-composer').evaluate(el => getComputedStyle(el).borderTopColor)
    const idle = await outline()
    await field.fill('测试输入')
    expect(await outline()).not.toBe(idle)
    await composer.getByRole('button', { name: '发送' }).click()
    await page.getByText('本地发送：测试输入').waitFor()
    await composer.getByRole('button', { name: '添加附件' }).click()
    await page.getByText('示例操作：选择附件').waitFor()

    await search.fill('WorkflowQueuePanel')
    await page.getByRole('button', { name: '清空全部' }).click()
    const confirmation = page.getByRole('alertdialog', { name: '确认清理队列' })
    await confirmation.getByRole('button', { name: '取消' }).click()
    await confirmation.waitFor({ state: 'hidden' })
  } finally {
    await browser.close()
    await server.close()
  }
}, 45000)
