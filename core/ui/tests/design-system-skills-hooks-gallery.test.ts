// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(技能和钩子操作只修改展厅数据)。
it('previews skill grouping and hook trust without touching real configuration', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    const search = page.getByLabel('搜索组件')
    await search.fill('CoreSkillsEditor')
    const skill = page.locator('[data-skill-card="sample-skill"]')
    await skill.getByRole('switch').click()
    expect(await skill.getByRole('switch').isChecked()).toBe(false)
    await skill.getByLabel('移动到分组').click()
    await page.getByRole('button', { name: '示例分组', exact: true }).click()
    await page.locator('[data-skill-filter="g:示例分组"]').click()
    expect(await skill.count()).toBe(1)
    await search.fill('CoreHooksEditor')
    const hook = page.locator('[data-hook-card="sample-hook"]')
    await hook.getByRole('button', { name: '信任', exact: true }).click()
    expect(await hook.innerText()).toContain('已信任')
    await hook.getByRole('button', { name: '取消', exact: true }).click()
    expect(await hook.innerText()).toContain('待审核')
    expect(await page.locator('.preview').innerText()).toContain('本地操作：hook.untrust')
  } finally { await browser.close(); await server.close() }
}, 120000)
