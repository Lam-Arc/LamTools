// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(下载页面只修改内存里的示例任务)。
it('tests real download controls with isolated tasks', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1100 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('NetworkTransfer')
    const row = page.locator('[data-task="sample-active"]')
    await row.getByRole('button', { name: '暂停下载' }).click()
    expect(await row.innerText()).toContain('已暂停')
    await row.getByRole('button', { name: '继续下载' }).click()
    expect(await row.innerText()).toContain('下载中')
    await row.getByRole('button', { name: '展开下载详情' }).click()
    await page.getByLabel('模拟限速失败').check()
    await page.getByLabel('下载速度限制').click()
    await page.getByRole('button', { name: '1 MB/s', exact: true }).click()
    expect(await page.getByLabel('下载速度限制').innerText()).toContain('不限速')
    await page.getByLabel('模拟限速失败').uncheck()
    await page.getByLabel('下载速度限制').click()
    await page.getByRole('button', { name: '1 MB/s', exact: true }).click()
    expect(await page.getByLabel('下载速度限制').innerText()).toContain('1 MB/s')
    expect(await page.locator('[data-local-network-action]').innerText()).toContain('1048576')
    await page.getByRole('button', { name: /已完成/ }).click()
    expect(await page.locator('[data-task="sample-complete"]').count()).toBe(1)
    expect(await row.count()).toBe(0)
    await page.getByLabel('下载链接').fill('https://example.test/sample.zip')
    await page.getByRole('button', { name: '开始下载' }).click()
    expect(await page.getByLabel('下载链接').inputValue()).toBe('')
    expect(await page.locator('[data-local-network-action]').innerText()).toContain('transfer.add')
    expect(await page.locator('[data-source-path="core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/TransferView.vue"]').count()).toBe(1)
  } finally { await browser.close(); await server.close() }
}, 120000)
