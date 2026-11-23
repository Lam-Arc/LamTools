// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(标记操作不接触真实会话)。
it('previews mark actions and empty state locally', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('MarksPanel')
    await page.getByRole('button', { name: '翻译', exact: true }).click()
    expect(await page.locator('.preview').innerText()).toContain('本地操作：翻译')
    await page.getByRole('button', { name: '示例标记文本' }).click()
    expect(await page.locator('.preview').innerText()).toContain('本地操作：定位')
    await page.getByRole('button', { name: '删除标记' }).click()
    expect(await page.locator('.study-marks').innerText()).toContain('选中文字后右键')
    await page.getByRole('button', { name: '重置示例' }).click()
    expect(await page.locator('.study-mark-row').count()).toBe(1)
  } finally { await browser.close(); await server.close() }
}, 120000)
