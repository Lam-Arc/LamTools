// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(验证网络图表与等待状态在两种主题可见)。
describe('network chart gallery browser', () => {
  it('renders local trend and waiting state in both themes', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 900 } }); page.setDefaultTimeout(5000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('SpeedChart')
      for (const theme of ['深色', '浅色']) {
        await page.getByLabel('预览主题').click(); await page.getByRole('button', { name: theme, exact: true }).click()
        const chart = page.getByRole('img', { name: '实时下载和上传速度趋势' })
        expect((await chart.boundingBox())!.width).toBeGreaterThan(100)
        expect(await page.locator('.nx-chart-download').getAttribute('d')).not.toContain('NaN')
        await page.locator('[data-network-chart-empty]').check()
        expect(await page.locator('.nx-chart-wait').innerText()).toContain('正在收集网速变化')
        await page.locator('[data-network-chart-empty]').uncheck()
      }
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
