// Debug the model menu: what the trigger shows, what the panel contains, what
// is actually visible after opening.  Used while building beats.
import { chromium } from 'playwright'

const browser = await chromium.connectOverCDP(`http://127.0.0.1:${process.env.DEMO_CDP_PORT || '9222'}`, { timeout: 20000 })
const context = browser.contexts()[0]
const page = context.pages()[0]

const trigger = page.locator('.core-model-thinking-menu__trigger')
console.log('trigger count:', await trigger.count())
if (await trigger.count()) {
  console.log('trigger text:', JSON.stringify((await trigger.first().innerText()).trim()))
  console.log('trigger visible:', await trigger.first().isVisible())
  await trigger.first().click()
  await page.waitForTimeout(800)
}

const report = await page.evaluate(() => {
  const collect = (selector, attribute) =>
    Array.from(document.querySelectorAll(selector)).map((node) => ({
      value: node.getAttribute(attribute),
      text: (node.textContent || '').trim().slice(0, 40),
      visible: Boolean(node.offsetParent) || node.getClientRects().length > 0,
    }))
  return {
    panels: Array.from(document.querySelectorAll('.core-model-thinking-menu__panel')).length,
    sections: collect('[data-model-thinking-section]', 'data-model-thinking-section'),
    submenus: collect('[data-model-thinking-submenu]', 'data-model-thinking-submenu'),
    providers: collect('[data-model-thinking-provider]', 'data-model-thinking-provider'),
    models: collect('[data-model-thinking-model-option]', 'data-model-thinking-model-option'),
    empty: (document.querySelector('.core-model-thinking-menu__empty') || {}).textContent || null,
  }
})
console.log(JSON.stringify(report, null, 2).slice(0, 4000))
await browser.close()
