// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(调用台只使用内存模型和结果，不读写真实参数)。
it('previews model selection, calls and history in isolation', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.evaluate(() => localStorage.setItem('lamtools.direct.params', '{"sample-text":{"temperature":0.1}}'))
    await page.getByLabel('搜索组件').fill('DirectCallView')
    await page.locator('[data-direct-input]').fill('示例问题')
    await page.locator('[data-direct-run]').click()
    expect(await page.locator('[data-direct-results]').innerText()).toContain('示例回答')
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('lamtools.direct.params')!)['sample-text'].temperature)).toBe(0.1)
    await page.locator('[data-direct-model="sample-image"]').click()
    expect(await page.getByLabel('尺寸').count()).toBe(1)
    await page.getByRole('tab', { name: '文本', exact: true }).click()
    expect(await page.locator('[data-direct-history="sample-call"]').count()).toBe(1)
    const remove = page.getByRole('button', { name: '删除记录 示例文本模型' })
    await remove.focus(); await page.keyboard.press('Enter')
    await expect.poll(() => page.locator('[data-direct-history="sample-call"]').count()).toBe(0)
    await page.getByLabel('模拟历史读取失败').check()
    await page.getByRole('tab', { name: '图片', exact: true }).click()
    expect(await page.locator('.direct-call [role="alert"]').innerText()).toContain('示例历史读取失败')
    await page.getByLabel('模拟历史读取失败').uncheck()
    await page.getByRole('tab', { name: '文本', exact: true }).click()
    expect(await page.locator('.direct-call [role="alert"]').count()).toBe(0)
  } finally { await browser.close(); await server.close() }
}, 120000)
