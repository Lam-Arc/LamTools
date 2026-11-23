// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(插件窗口示例不启动真实桌面窗口)。
it('previews card and unmatched plugin windows without duplicate entries', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('CorePluginSystemEditor')
    const card = page.getByRole('button', { name: '示例插件窗口', exact: true })
    await card.waitFor()
    expect(await card.count()).toBe(1)
    const orphan = page.getByRole('button', { name: '其他示例窗口', exact: true })
    await orphan.click()
    expect(await page.locator('.preview').innerText()).toContain('插件窗口只能在桌面端打开')
    expect(await page.locator('[data-source-path="core/ui/src/components/PluginWindowLauncher.vue"]').count()).toBe(1)
  } finally { await browser.close(); await server.close() }
}, 120000)
