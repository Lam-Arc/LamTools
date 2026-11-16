// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(检查真实项目设置的名称与规则在深浅主题可编辑)。
describe('project settings gallery browser', () => {
  it('edits local name and rules under both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreProjectSettings')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const name = page.locator('[data-project-name-input]'); await name.fill(`示例${theme}`); await name.press('Enter')
        expect(await page.locator('.preview').innerText()).toContain(`本地项目：示例${theme}`)
        const rules = page.locator('.preview textarea'); await rules.fill(`规则${theme}`)
        const card = page.locator('.preview .setting-card').filter({ hasText: '项目规则' })
        await card.getByRole('button', { name: '保存', exact: true }).click()
        expect(await page.locator('.preview').innerText()).toContain('本地规则已保存')
        expect(await rules.inputValue()).toBe(`规则${theme}`)
      }
      const rules = page.locator('.preview textarea')
      await rules.fill('未保存的规则')
      await page.locator('[data-settings-section="subagent"]').click()
      const dialog = page.getByRole('dialog')
      await dialog.getByRole('button', { name: '取消' }).click()
      expect(await rules.inputValue()).toBe('未保存的规则')
      expect(await page.locator('[data-settings-section="subagent"]').getAttribute('aria-current')).not.toBe('page')
      await page.locator('[data-settings-section="subagent"]').click()
      await page.getByRole('dialog').getByRole('button', { name: '丢弃修改' }).click()
      await page.locator('[data-settings-section="project"]').click()
      expect(await page.locator('.preview textarea').inputValue()).toBe('规则浅色')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})

