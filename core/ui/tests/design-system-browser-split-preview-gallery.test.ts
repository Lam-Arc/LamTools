// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“直接渲染项目真实组件…交互测试”+(文件预览切换类型与失败重试均使用本地数据)。
describe('split file preview gallery', () => {
  it('previews markdown and text, handles errors, and simulates external opening', async () => {
    const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
    const browser = await chromium.launch({ headless: true })
    try {
      const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } }); page.setDefaultTimeout(10000)
      await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
      await page.getByLabel('搜索组件').fill('CoreSplitPreview')
      const preview = page.locator('[data-gallery-file-preview]')
      expect(await preview.innerText()).toContain('示例标题')
      await page.getByRole('button', { name: '文本示例' }).click()
      expect(await preview.innerText()).toContain('示例纯文本')
      await page.getByLabel('模拟读取失败').check(); await preview.getByRole('button', { name: '重新读取' }).click()
      expect(await preview.getByRole('alert').innerText()).toContain('示例读取失败')
      await page.getByLabel('模拟读取失败').uncheck(); await preview.getByRole('button', { name: '重试' }).click()
      expect(await preview.innerText()).toContain('示例纯文本')
      await page.getByRole('button', { name: '图片示例' }).click()
      // user:“灯箱有的，分屏也该有”+(图片交给共用查看器：缩放、拖动、双击、标注都在它里面，
      //  所以这里按查看器自己的工具坞来验，分屏工具条不再重复一套缩放按钮)。
      const stage = preview.locator('[data-preview-image]'); await stage.waitFor()
      expect(await preview.getByRole('button', { name: '标注', exact: true }).count()).toBe(1)
      expect(await preview.getByRole('button', { name: '复制' }).count()).toBe(1)
      const percent = stage.locator('[data-preview-zoom-percent]')
      await preview.getByRole('button', { name: '放大', exact: true }).click()
      await expect.poll(async () => await percent.innerText()).toContain('125')
      await preview.getByRole('button', { name: '适应窗口', exact: true }).click()
      await expect.poll(async () => await percent.innerText()).toContain('100')
      await preview.getByRole('button', { name: '使用默认应用打开' }).click()
      expect(await page.locator('.preview').innerText()).toContain('本地模拟打开')
    } finally { await browser.close(); await server.close() }
  }, 60000)
})
