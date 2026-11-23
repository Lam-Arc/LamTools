// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(笔记树导航只更新展厅中的本地选择)。
it('previews the real note tree, keyboard navigation and error state', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('StudyNoteTree')
    const folder = page.getByRole('treeitem', { name: '示例课程' })
    await folder.focus(); await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowRight')
    const note = page.getByRole('treeitem', { name: '示例笔记' })
    expect(await note.evaluate(el => document.activeElement === el)).toBe(true)
    await page.keyboard.press('Enter')
    expect(await page.locator('.preview').innerText()).toContain('本地选择：示例笔记')
    await page.getByLabel('模拟读取失败').check()
    expect(await page.getByRole('alert').innerText()).toContain('示例读取失败')
    await page.getByRole('button', { name: '刷新笔记文件树' }).click()
    expect(await page.getByRole('alert').count()).toBe(0)
  } finally { await browser.close(); await server.close() }
}, 120000)
