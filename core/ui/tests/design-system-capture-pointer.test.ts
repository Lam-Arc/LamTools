// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“确保视觉、功能和交互不退化”+(标注拖出画布后松开仍能完成并撤销)。
it('finishes an arrow when the pointer is released outside the canvas', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 900 } }); page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('CaptureEditor')
    await page.locator('[data-load-capture]').click()
    const capture = page.locator('.capture--sandbox'), canvas = capture.locator('canvas')
    await capture.getByRole('button', { name: '箭头' }).click()
    const box = (await canvas.boundingBox())!
    await page.mouse.move(box.x + 30, box.y + 30); await page.mouse.down()
    await page.mouse.move(box.x + 100, box.y + 100)
    await page.mouse.move(box.x - 20, box.y - 20); await page.mouse.up()
    const afterRelease = await canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL())
    await page.mouse.move(box.x + 150, box.y + 120)
    expect(await canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL())).toBe(afterRelease)
    await capture.getByRole('button', { name: '撤销' }).click()
    expect(await canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL())).not.toBe(afterRelease)
    await capture.getByRole('button', { name: '重做' }).click()
    expect(await canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL())).toBe(afterRelease)
    await capture.getByRole('button', { name: '清空' }).click()
    expect(await canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL())).not.toBe(afterRelease)
  } finally { await browser.close(); await server.close() }
}, 120000)
