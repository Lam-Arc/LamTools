// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(订阅、测速和节点切换只使用本地示例)。
it('previews subscription and node selection without network access', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('NetworkProxy')
    await page.getByRole('button', { name: '添加订阅', exact: true }).first().click()
    await page.getByLabel('订阅链接', { exact: true }).fill('https://example.test/subscription')
    await page.getByLabel('模拟取消保存').check()
    await page.getByRole('button', { name: '保存订阅' }).click()
    expect(await page.getByLabel('订阅链接', { exact: true }).inputValue()).toBe('https://example.test/subscription')
    await page.getByLabel('模拟取消保存').uncheck()
    await page.getByRole('button', { name: '保存订阅' }).click()
    expect(await page.locator('[data-profile-import]').count()).toBe(0)
    await page.getByLabel('代理连接').click()
    expect(await page.locator('[data-node="示例线路 B"]').count()).toBe(1)
    await page.locator('[data-node="示例线路 B"]').click()
    expect(await page.locator('[data-node="示例线路 B"]').getAttribute('aria-pressed')).toBe('true')
    await page.getByRole('button', { name: '测试 示例线路 B 的延迟' }).click()
    expect(await page.locator('[data-node="示例线路 B"]').innerText()).toContain('48 ms')
    expect(await page.locator('[data-source-path="core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/ImportProfile.vue"]').count()).toBe(1)
  } finally { await browser.close(); await server.close() }
}, 120000)
