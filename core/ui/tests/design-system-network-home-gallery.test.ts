// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(网络首页只操作隔离的示例数据)。
it('exercises real network home actions without network services', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('NetworkHome')
    const home = page.locator('[data-home-block="acceleration"]')
    expect((await home.boundingBox())!.width).toBeGreaterThan(200)
    await home.getByRole('button', { name: '一键加速' }).click()
    expect(await home.innerText()).toContain('运行中')
    await page.locator('[data-home-proxy]').click()
    expect(await page.locator('.preview').innerText()).toContain('本地导航：proxy')
    await page.getByLabel('模拟已有订阅').check()
    await page.locator('[data-home-proxy]').click()
    expect(await page.locator('[data-home-block="proxy"]').innerText()).toContain('已连接')
    await page.getByLabel('下载链接').fill('https://example.test/file.zip')
    await page.getByLabel('模拟下载失败').check()
    await page.getByRole('button', { name: '开始下载' }).click()
    expect(await page.getByLabel('下载链接').inputValue()).toBe('https://example.test/file.zip')
    await page.getByLabel('模拟下载失败').uncheck()
    await page.getByLabel('模拟处理中').check()
    expect(await page.getByRole('button', { name: '开始下载' }).isDisabled()).toBe(true)
    await page.getByLabel('模拟处理中').uncheck()
    await page.getByRole('button', { name: '开始下载' }).click()
    expect(await page.locator('[data-home-block="transfer"]').innerText()).toContain('1 个任务')
    expect(await page.getByLabel('下载链接').inputValue()).toBe('')
    expect(await page.locator('[data-source-path="core/src/lamtools_core/plugins/bundled/network-exploration/ui/src/HomeView.vue"]').count()).toBe(1)
    await page.getByLabel('预览主题').click()
    await page.getByRole('button', { name: '浅色', exact: true }).click()
    expect(await home.innerText()).toContain('运行中')
    expect((await home.boundingBox())!.width).toBeGreaterThan(200)
  } finally { await browser.close(); await server.close() }
}, 120000)
