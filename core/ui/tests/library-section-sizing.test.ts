// @vitest-environment node
import { readFileSync } from 'node:fs'
import { chromium } from 'playwright'
import { expect, it } from 'vitest'

it('keeps library section buttons fully visible in a narrow split with long content', async () => {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage()
    await page.setContent(`
      <div class="core-app-page core-app-page--auxiliary" style="width: 260px; height: 230px">
        <div class="library-surface full-area-view library-home">
          <div class="library-sections sunday-page-tabs" style="--interaction-height-sm: 28px; --space-1: 4px; --space-2: 8px; --space-4: 16px">
            ${['资料', '项目文件', '记忆', '方案', 'Wiki'].map(label => `<button>${label}</button>`).join('')}
          </div>
          <section style="min-height: 700px">资料列表</section>
        </div>
      </div>
    `)
    for (const path of ['layout.css', 'page-surfaces.css', 'library-surface.css', 'app-page.css']) {
      await page.addStyleTag({ content: readFileSync(`src/styles/${path}`, 'utf8') })
    }
    const sizes = await page.locator('.library-home').evaluate(container => {
      const bar = container.querySelector<HTMLElement>('.library-sections')!
      const button = bar.querySelector('button')!.getBoundingClientRect()
      const rect = bar.getBoundingClientRect()
      return { buttonTop: button.top, buttonBottom: button.bottom, barTop: rect.top, barBottom: rect.bottom, scrolls: container.scrollHeight > container.clientHeight }
    })
    expect(sizes.buttonTop).toBeGreaterThanOrEqual(sizes.barTop)
    expect(sizes.buttonBottom).toBeLessThanOrEqual(sizes.barBottom)
    expect(sizes.scrolls).toBe(true)
  } finally { await browser.close() }
})
