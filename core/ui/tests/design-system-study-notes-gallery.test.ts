// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(笔记编辑、保存和切换只操作内存示例)。
it('tests note editing, failed save and draft-protected navigation', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('NotesManager')
    const workspace = page.getByLabel('Markdown 笔记工作区')
    await workspace.getByRole('button', { name: '编辑', exact: true }).click()
    const editor = page.getByLabel('编辑笔记全文')
    await editor.fill('# 草稿\n\n[[note-b|另一篇笔记]]')
    await page.getByLabel('模拟保存失败').check()
    await workspace.getByRole('button', { name: '保存', exact: true }).click()
    expect(await workspace.getByRole('alert').innerText()).toContain('示例保存失败')
    expect(await editor.inputValue()).toContain('草稿')
    await page.getByLabel('模拟保存失败').uncheck()
    await workspace.getByRole('button', { name: '预览', exact: true }).click()
    await workspace.getByRole('link', { name: '另一篇笔记' }).click()
    const dialog = page.getByRole('dialog', { name: '放弃未保存的修改？' })
    await dialog.getByRole('button', { name: '取消' }).click()
    expect(await workspace.innerText()).toContain('未保存')
    await workspace.getByRole('button', { name: '保存', exact: true }).click()
    expect(await workspace.innerText()).toContain('已保存')
    await workspace.getByRole('link', { name: '另一篇笔记' }).click()
    expect(await workspace.locator('[data-note-id="note-b"]').count()).toBe(1)
    await page.getByRole('button', { name: '模拟远程更新' }).click()
    expect(await workspace.innerText()).toContain('示例远程更新')
  } finally { await browser.close(); await server.close() }
}, 120000)
