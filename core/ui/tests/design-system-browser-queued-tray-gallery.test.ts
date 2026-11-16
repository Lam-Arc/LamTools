// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(队列编辑和引导只作用于内存示例)。
describe('queued input gallery', () => {
  it('edits, cancels and dispatches local queued input', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreQueuedInputTray')
      const row = page.locator('.core-queued-input-row').first(); await row.waitFor()
      await page.getByLabel('允许引导').uncheck()
      expect(await row.getByRole('button', { name: '作为引导发送' }).isDisabled()).toBe(true)
      await page.getByLabel('允许引导').check()
      const edit = row.getByRole('button', { name: '编辑待发送内容' }); await edit.focus()
      expect(await row.locator('.core-queued-input-ellipsis').evaluate(el => getComputedStyle(el).pointerEvents)).toBe('none')
      await edit.click(); const input = row.locator('[data-queued-input-edit]'); await input.fill('修改后的示例')
      await input.press('Escape'); expect(await row.innerText()).toContain('整理资料')
      await edit.focus(); await edit.click(); await input.fill('修改后的示例'); await input.press('Enter')
      expect(await row.innerText()).toContain('修改后的示例')
      const second = page.locator('.core-queued-input-row').nth(1)
      const from = (await second.boundingBox())!, to = (await row.boundingBox())!
      await page.mouse.move(from.x + 15, from.y + from.height / 2); await page.mouse.down()
      await page.mouse.move(to.x + 15, to.y + 4, { steps: 15 }); await page.mouse.up()
      expect(await page.locator('.core-queued-input-row').first().innerText()).toContain('检查结果')
      const editedRow = page.locator('.core-queued-input-row').filter({ hasText: '修改后的示例' })
      await editedRow.getByRole('button', { name: '作为引导发送' }).focus()
      await editedRow.getByRole('button', { name: '作为引导发送' }).click()
      expect(await page.locator('.preview').innerText()).toContain('本地引导：修改后的示例')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
