// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(连接和检测结果均为本地数据)。
it('tests connection search and diagnostics using local data', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    const search = page.getByLabel('搜索组件')
    await search.fill('NetworkConnections')
    await page.getByLabel('搜索连接').fill('浏览器')
    await page.locator('.nx-searchbar').getByRole('button', { name: '刷新' }).click()
    expect(await page.locator('.nx-table').innerText()).toContain('示例浏览器')
    expect(await page.locator('.nx-table').innerText()).not.toContain('示例工具')
    await page.getByLabel('搜索连接').fill('不存在')
    await page.locator('.nx-searchbar').getByRole('button', { name: '刷新' }).click()
    expect(await page.locator('.nx-empty').innerText()).toContain('没有匹配的连接')
    await search.fill('NetworkDiagnose')
    await page.getByLabel('检测网站').fill('example.test')
    await page.getByLabel('加测延迟').check()
    await page.getByRole('button', { name: '开始检测' }).click()
    expect(await page.locator('.nx-report').innerText()).toContain('example.test')
    await page.getByRole('button', { name: '查看检查详情' }).click()
    expect(await page.locator('.nx-check-evidence').innerText()).toContain('示例地址')
    expect(await page.locator('.preview').innerText()).toContain('本地检查方式：ping')
  } finally { await browser.close(); await server.close() }
}, 120000)
