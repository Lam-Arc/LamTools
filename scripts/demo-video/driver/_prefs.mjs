import { chromium } from 'playwright'
const browser = await chromium.connectOverCDP('http://127.0.0.1:9222', { timeout: 20000 })
const page = browser.contexts()[0].pages()[0]
const out = await page.evaluate(() => ({
  prefs: localStorage.getItem('lamtools.core.ui.preferences'),
  legacy: localStorage.getItem('lamtools.core.ui'),
  rootAttrs: {
    theme: document.documentElement.getAttribute('data-theme'),
    mode: document.documentElement.getAttribute('data-theme-mode'),
    preset: document.documentElement.getAttribute('data-theme-preset'),
  },
  bodyBg: getComputedStyle(document.body).backgroundColor,
}))
console.log(JSON.stringify(out, null, 1).slice(0, 1200))
await browser.close()
