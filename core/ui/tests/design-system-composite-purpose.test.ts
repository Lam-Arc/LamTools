// @vitest-environment node
import { chromium } from 'playwright'
import { expect, it } from 'vitest'
import { createServer } from 'vite'

// user:“按聊天、设置、文件、工作流等实际用途再分一层”+(所有组合都有用途；筛选、搜索和直达链接共用同一分类)。
it('filters page previews by purpose and combines purpose with search', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
  await server.listen()
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ viewport: { width: 1320, height: 900 } })
    page.setDefaultTimeout(10000)
    const url = server.resolvedUrls!.local[0] + 'design-system.html'
    await page.goto(url + '?category=' + encodeURIComponent('组合'))
    const cards = page.locator('.specimen')
    const groupTags = cards.locator('[data-composite-group]')
    await groupTags.first().waitFor()
    expect(await groupTags.count()).toBe(61)
    expect(new Set(await groupTags.allTextContents()).size).toBe(9)

    await page.getByLabel('组合用途').click()
    await page.locator('.ui-select-menu').getByRole('button', { name: '文件与资料（8）' }).click()
    expect(await cards.count()).toBe(8)
    const search = page.getByLabel('搜索组件')
    await search.fill('CoreSplitFileTree')
    expect(await cards.count()).toBe(1)
    await search.fill('MessageView')
    expect(await cards.count()).toBe(0)

    await page.goto(url + '?category=' + encodeURIComponent('组合') + '&group=' + encodeURIComponent('工作流与任务'))
    await page.locator('#specimen-WorkflowCanvas').waitFor()
    expect(await cards.count()).toBe(7)
    expect(await page.locator('#specimen-MessageView').count()).toBe(0)
    await page.getByLabel('组件分类').click()
    await page.locator('.ui-select-menu').getByRole('button', { name: '按钮', exact: true }).click()
    expect(await page.getByLabel('组合用途').count()).toBe(0)
    expect(await cards.count()).toBe(2)
  } finally {
    await browser.close()
    await server.close()
  }
}, 30000)
