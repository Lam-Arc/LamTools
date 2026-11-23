// @vitest-environment node
import { expect, it } from 'vitest'
import { createServer } from 'vite'
import { chromium } from 'playwright'

// user:“灯箱应该配套缩放UI，支持Ctrl滚轮，提供复制/外部打开键，默认大小自适应，左键可拖动”+
// user:“支持修改标注…『引用』，直接将已标注/未标注则为原图直接加入输入框”+
// (展厅里跑真实灯箱与真实查看器：自适应、Ctrl+滚轮、拖动、标注与“复制标注图”都走真手势)。
it('zooms, pans, annotates and copies the lightbox image', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } }); await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({
      viewport: { width: 1400, height: 1000 },
      reducedMotion: 'reduce',
      permissions: ['clipboard-read', 'clipboard-write'],
    })
    page.setDefaultTimeout(15000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html')
    await page.getByLabel('搜索组件').fill('PreviewLightbox')
    await page.getByRole('button', { name: '打开图片示例' }).click()

    const dialog = page.getByRole('dialog', { name: '预览：图片示例.png' })
    await dialog.waitFor()
    const stage = dialog.locator('[data-preview-image]')
    const image = stage.locator('img')
    await expect.poll(() => image.evaluate(element => (element as HTMLImageElement).naturalWidth)).toBe(1600)

    const percent = stage.locator('[data-preview-zoom-percent]')
    const initial = await percent.innerText()
    // 1600×1000 装进灯箱后必须缩到 100% 以下；小图另测（纯函数里已覆盖 1:1）。
    expect(Number.parseInt(initial, 10)).toBeLessThan(100)

    const stageBox = (await stage.boundingBox())!
    const center = { x: stageBox.x + stageBox.width / 2, y: stageBox.y + stageBox.height / 2 }

    // user:“把ctrl加滚轮改成滚轮控制”+(滚轮直接缩放，不再需要按 Ctrl)。
    await page.mouse.move(center.x, center.y)
    await page.mouse.wheel(0, -500)
    await expect.poll(async () => Number.parseInt(await percent.innerText(), 10)).toBeGreaterThan(Number.parseInt(initial, 10))
    const zoomed = Number.parseInt(await percent.innerText(), 10)

    // 左键拖动：位置真的变了（必须在放大之后拖，装得下时是居中的、拖不动）。
    const beforeDrag = await image.evaluate(element => getComputedStyle(element).transform)
    await page.mouse.move(center.x, center.y)
    await page.mouse.down()
    await page.mouse.move(center.x - 140, center.y - 90, { steps: 6 })
    await page.mouse.up()
    const afterDrag = await image.evaluate(element => getComputedStyle(element).transform)
    expect(afterDrag).not.toBe(beforeDrag)

    // 往回滚是缩小（同一档位、同一锚点，不跳）。
    await page.mouse.wheel(0, 500)
    await expect.poll(async () => Number.parseInt(await percent.innerText(), 10)).toBeLessThan(zoomed)

    // 适应：回到打开时的档位。
    await dialog.getByRole('button', { name: '适应窗口' }).click()
    await expect.poll(async () => await percent.innerText()).toBe(initial)

    // 标注：共用工具条出现，画一条箭头后计数从 0 变 1，可撤销/重做。
    await dialog.getByRole('button', { name: '标注', exact: true }).click()
    const tools = dialog.locator('[data-preview-annotate-tools]')
    await tools.waitFor()
    await tools.getByRole('button', { name: '箭头' }).click()
    await page.mouse.move(center.x - 120, center.y - 70)
    await page.mouse.down()
    await page.mouse.move(center.x + 90, center.y + 50, { steps: 8 })
    await page.mouse.up()
    await expect.poll(() => stage.getAttribute('data-annotations')).toBe('1')
    await tools.getByRole('button', { name: '撤销' }).click()
    expect(await stage.getAttribute('data-annotations')).toBe('0')
    await tools.getByRole('button', { name: '重做' }).click()
    expect(await stage.getAttribute('data-annotations')).toBe('1')

    // 复制标注图：合成 PNG 后写进剪贴板，头部给出结果。
    await dialog.getByRole('button', { name: '复制', exact: true }).click()
    await expect.poll(() => page.locator('[data-preview-hint]').innerText()).toContain('已复制标注图')

    // user:“标注后无法引用”+(标注后走的是“合成图上传”这条链路：引用必须真的交出
    // 一张能解码的 PNG，而不是原图或空文件；交出后灯箱自行关闭)。
    await dialog.getByRole('button', { name: '引用', exact: true }).click()
    const receipt = page.locator('[data-gallery-reference]')
    await expect.poll(() => receipt.getAttribute('data-name')).toBe('图片示例-标注.png')
    expect(await receipt.getAttribute('data-type')).toBe('image/png')
    expect(Number(await receipt.getAttribute('data-size'))).toBeGreaterThan(1000)
    await expect.poll(() => receipt.getAttribute('data-decodable')).toBe('true')
    await expect.poll(() => page.locator('[data-preview-lightbox]').count()).toBe(0)

    // 再打开一次：Esc 仍然关灯箱（标注模式下 Esc 只退出标注，这里已不在标注态）。
    await page.getByRole('button', { name: '打开图片示例', exact: true }).click()
    await page.getByRole('dialog', { name: '预览：图片示例.png' }).waitFor()
    await page.keyboard.press('Escape')
    await expect.poll(() => page.locator('[data-preview-lightbox]').count()).toBe(0)
  } finally { await browser.close(); await server.close() }
}, 180000)
