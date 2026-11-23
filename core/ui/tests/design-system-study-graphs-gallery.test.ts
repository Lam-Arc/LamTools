// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(图谱操作只更新展厅里的示例)。
it('previews knowledge graph and note relations with keyboard access', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    const search = page.getByLabel('搜索组件')
    await search.fill('StudyGraph')
    const node = page.locator('[data-study-node="concept"]')
    await node.focus(); await page.keyboard.press('Enter')
    expect(await page.locator('.preview').innerText()).toContain('本地打开：示例知识点 · 1 次')
    await node.click()
    expect(await page.locator('.preview').innerText()).toContain('本地打开：示例知识点 · 2 次')
    await node.focus(); await page.keyboard.press('Space')
    expect(await page.locator('.preview').innerText()).toContain('本地打开：示例知识点 · 3 次')
    await page.getByRole('button', { name: '放大', exact: true }).click()
    expect(await page.locator('.preview').innerText()).toContain('本地缩放：1.20')
    await search.fill('StudyNoteRelationGraph')
    const relation = page.locator('[data-note-graph-node="b"]')
    await relation.focus(); await page.keyboard.press('Enter')
    expect(await page.locator('.preview').innerText()).toContain('本地打开：b')
    await page.getByLabel('空关系图').check()
    expect(await page.locator('.study-note-graph-empty').innerText()).toContain('暂无笔记关系')
  } finally { await browser.close(); await server.close() }
}, 120000)
