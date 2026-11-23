// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(网络设置、防护与计划均使用内存示例)。
it('previews DNS, protection and scheduled checks without changing the system', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1100 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    const search = page.getByLabel('搜索组件')
    await search.fill('NetworkSettings')
    await page.getByLabel('查询域名').fill('example.test')
    await page.getByRole('button', { name: '查询', exact: true }).click()
    expect(await page.locator('.nx-query-result').innerText()).toContain('192.0.2.1')
    await page.getByRole('button', { name: '调整 DNS', exact: true }).click()
    expect(await page.getByRole('button', { name: '确认并申请修改' }).isDisabled()).toBe(true)
    await search.fill('NetworkSecurity')
    await page.getByRole('button', { name: '恢复', exact: true }).click()
    expect(await page.locator('.nx-transaction').innerText()).toContain('已恢复')
    await search.fill('NetworkAdvanced')
    await page.getByRole('button', { name: '添加', exact: true }).click()
    await page.getByLabel('定时检查的网站').fill('example.test')
    await page.getByRole('button', { name: '添加计划' }).click()
    expect(await page.locator('.nx-schedule-row').innerText()).toContain('example.test')
    await page.getByRole('button', { name: '查看设备', exact: true }).click()
    expect(await page.locator('.nx-table').innerText()).toContain('192.0.2.10')
  } finally { await browser.close(); await server.close() }
}, 120000)
