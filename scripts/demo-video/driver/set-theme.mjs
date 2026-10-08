// Put the demo window into the look the video must use: 默认 preset, light mode.
//
//   node scripts/demo-video/driver/set-theme.mjs [--preset default] [--mode light] [--density standard]
//
// Idempotent: it reports the state it ended in, so a take can assert the look
// before recording instead of discovering a dark theme in the footage.
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { applyDemoLayout, assertForeground, sizeDemoWindow } from './sunday.mjs'

const args = process.argv.slice(2)
const value = (name, fallback) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? fallback : args[index + 1]
}
const PRESET = value('preset', 'default')
const MODE = value('mode', 'light')
const DENSITY = value('density', 'standard')
const OUT = value('out', 'E:/LamDemo/probe')

const browser = await chromium.connectOverCDP(`http://127.0.0.1:${process.env.DEMO_CDP_PORT || '9222'}`, { timeout: 20000 })
const context = browser.contexts()[0]
const page = context.pages()[0]
sizeDemoWindow()
await applyDemoLayout(context, page)
await assertForeground(page)

async function openAppearance() {
  const rail = page.locator('[data-rail-entry="settings"]')
  if (await rail.count()) {
    await rail.first().click()
    await page.waitForTimeout(900)
  }
  const section = page.locator('[data-nav-section="appearance"]')
  if (await section.count()) {
    await section.first().click()
    await page.waitForTimeout(700)
  }
}

async function pick(attribute, wanted) {
  const target = page.locator(`[${attribute}="${wanted}"]`)
  if (!(await target.count())) return `missing ${attribute}=${wanted}`
  await target.first().click()
  await page.waitForTimeout(450)
  return 'ok'
}

await openAppearance()
console.log('mode  :', await pick('data-theme-mode', MODE))
console.log('preset:', await pick('data-theme-preset', PRESET))
console.log('density:', await pick('data-density', DENSITY))

const state = await page.evaluate(() => {
  const active = (attribute) => {
    const node = document.querySelector(`[${attribute}][aria-pressed="true"], [${attribute}].active`)
    return node ? node.getAttribute(attribute) : null
  }
  return {
    mode: active('data-theme-mode'),
    preset: active('data-theme-preset'),
    density: active('data-density'),
    background: getComputedStyle(document.body).backgroundColor,
  }
})
console.log('state:', JSON.stringify(state))

fs.mkdirSync(OUT, { recursive: true })
await page.screenshot({ path: path.join(OUT, 'theme-check.png') })
// Back to the workspace so the next step starts where a take expects to be.
const chat = page.locator('[data-rail-entry="chat"]')
if (await chat.count()) {
  await chat.first().click()
  await page.waitForTimeout(700)
}
await browser.close()
