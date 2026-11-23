// @vitest-environment node
import { expect, it } from 'vitest'
import { chromium } from 'playwright'
import { createServer } from 'vite'

// user:“确保视觉、功能和交互不退化”+(共享控件接入真实组件后，仍能选语言、翻译和操作传输)。
it('exercises shared controls in the capture and device transfer previews', async () => {
  const server = await createServer({ configFile: 'vite.config.ts', server: { port: 0 } })
  await server.listen()
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
    page.setDefaultTimeout(10000)
    await page.goto(server.resolvedUrls!.local[0] + 'design-system.html', { waitUntil: 'domcontentloaded' })
    const search = page.getByLabel('搜索组件')
    await search.fill('CaptureEditor')
    await page.locator('[data-load-capture]').click()
    await page.getByRole('button', { name: '提取文字', exact: true }).click()
    const panel = page.getByRole('dialog', { name: '提取文字' })
    const source = panel.getByRole('button', { name: '原文语言' })
    const target = panel.getByRole('button', { name: '目标语言' })
    expect(await source.innerText()).toBe('自动检测')
    await target.click()
    expect(await page.locator('.ui-select-menu').getByRole('button', { name: '自动检测' }).count()).toBe(0)
    await page.keyboard.press('Escape')
    expect(await target.getAttribute('aria-expanded')).toBe('false')
    expect(await panel.isVisible()).toBe(true)
    await target.click()
    await page.locator('.ui-select-menu').getByRole('button', { name: '英语' }).click()
    await panel.getByRole('button', { name: '翻译', exact: true }).click()
    await page.getByText('用 示例模型 翻译', { exact: false }).waitFor()
    await page.keyboard.press('Escape')
    expect(await panel.isVisible()).toBe(false)

    await search.fill('TransferPanel')
    const transfer = page.locator('[data-transfer-panel]')
    const progress = transfer.getByRole('progressbar', { name: '示例报告.pdf' })
    expect(await progress.getAttribute('aria-valuenow')).toBe('50')
    await transfer.locator('[data-transfer-cancel="sample-transfer"]').click()
    await transfer.getByText('已取消').waitFor()
    await transfer.locator('[data-transfer-retry="sample-transfer"]').click()
    await page.getByText('示例操作：重试传输').waitFor()

    await search.fill('SendToDeviceMenu')
    const device = page.locator('[data-send-device="sample-online"]')
    expect(await page.locator('[data-send-device="sample-offline"]').isDisabled()).toBe(true)
    await device.click()
    await page.getByText('示例操作：开始传输').waitFor()

    await search.fill('AccountShell')
    const autoConnect = page.getByRole('checkbox', { name: '启动时自动开启远程访问' })
    await autoConnect.check()
    expect(await autoConnect.evaluate(element => element.classList.contains('sunday-checkbox'))).toBe(true)
    expect(await autoConnect.isChecked()).toBe(true)
  } finally {
    await browser.close()
    await server.close()
  }
}, 120000)

