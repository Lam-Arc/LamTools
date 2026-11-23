// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(解释和翻译由隔离的本地示例模拟)。
it('previews selection explanation, errors and close without external requests', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('SelectionAssistant')
    await page.getByLabel('模拟回答失败').check()
    await page.getByRole('button', { name: '打开解释示例' }).click()
    const dialog = page.getByRole('dialog', { name: '解释' })
    await dialog.locator('.selection-answer').getByRole('button', { name: '解释' }).click()
    await expect.poll(async () => await page.locator('.selection-card').allTextContents()).toContainEqual(expect.stringContaining('示例回答失败'))
    await dialog.getByRole('button', { name: '关闭' }).click()
    await page.getByLabel('模拟回答失败').uncheck()
    await page.getByRole('button', { name: '打开解释示例' }).click()
    await dialog.locator('.selection-answer').getByRole('button', { name: '解释' }).click()
    expect(await dialog.innerText()).toContain('这是本地示例解释')
    await dialog.getByRole('button', { name: '翻译', exact: true }).click()
    const translation = page.getByRole('dialog', { name: '翻译' })
    await translation.locator('.selection-answer').getByRole('button', { name: '翻译' }).click()
    expect(await translation.innerText()).toContain('这是本地示例翻译')
    await page.keyboard.press('Escape')
    expect(await translation.count()).toBe(0)
  } finally { await browser.close(); await server.close() }
}, 120000)
