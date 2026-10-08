import { chromium } from 'playwright'
import { createActor, applyDemoLayout, assertForeground } from './sunday.mjs'
import { pickModel, DEFAULT_MODEL } from '../beats/_lib.mjs'

const browser = await chromium.connectOverCDP('http://127.0.0.1:9222', { timeout: 20000 })
const context = browser.contexts()[0]
const page = context.pages()[0]
await applyDemoLayout(context, page)
await assertForeground(page)
const actor = createActor(page)
const ctx = { page, actor, note: (m) => console.log('note:', m) }
try {
  await pickModel(ctx, { model: DEFAULT_MODEL })
  const shown = (await page.locator('.core-model-thinking-menu__trigger').first().innerText()).replace(/\n/g, ' ')
  console.log('RESULT trigger now shows:', shown)
} catch (e) {
  console.log('FAILED:', String(e.message).split('\n')[0])
}
await browser.close()
