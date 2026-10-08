import { chromium } from 'playwright'
const browser = await chromium.connectOverCDP('http://127.0.0.1:9222', { timeout: 15000 })
const page = browser.contexts()[0].pages()[0]
const s = await page.evaluate(() => ({
  state: document.querySelector('.core-send-stop-button')?.dataset.state,
  draft: (document.querySelector('.composer-input-wrap textarea')?.value || '').slice(0, 60),
  queued: document.querySelectorAll('[data-queued-input-edit]').length,
}))
console.log(JSON.stringify(s))
await browser.close()
