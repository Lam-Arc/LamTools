// Answer a pending decision in the live demo window.
//
//   node scripts/demo-video/answer-decision.mjs                 # print what is being asked
//   node scripts/demo-video/answer-decision.mjs "选项文字"       # click the matching option
//
// The agent may park a turn on a question (decision=wait); the window shows the
// options as buttons.  This clicks one of them by its visible text.

import { connectSunday, sleep } from './driver/sunday.mjs'

const label = process.argv[2] || ''

const { page } = await connectSunday()

// The question may render as a panel or as an inline part in the thread, so look
// for the option text itself and report the smallest element that carries it.
const probe = label || '按计划'
const hits = await page.evaluate((needle) => {
  const out = []
  const walk = (el) => {
    const text = (el.textContent || '').trim()
    if (!text.includes(needle)) return
    const kids = Array.from(el.children)
    if (kids.some((k) => (k.textContent || '').includes(needle))) {
      kids.forEach(walk)
      return
    }
    out.push({
      tag: el.tagName,
      cls: el.className && typeof el.className === 'string' ? el.className : '',
      role: el.getAttribute('role') || '',
      text: text.slice(0, 120),
    })
  }
  walk(document.body)
  return out.slice(0, 12)
}, probe)

if (!hits.length) {
  console.log(`DOM 里找不到含「${probe}」的元素`)
  const body = await page.locator('body').innerText()
  console.log(body.slice(0, 400))
  process.exit(0)
}
console.log('候选元素:')
hits.forEach((h, i) => console.log(`  ${i + 1}. <${h.tag}> class="${h.cls}" role="${h.role}" :: ${h.text}`))

if (!label) process.exit(0)

const button = page.locator('button.pending-decision__option', { hasText: label }).first()
const target = (await button.count()) ? button : page.getByText(label, { exact: false }).first()
await target.waitFor({ state: 'visible', timeout: 15000 })
await target.evaluate((el) => el.click())
await sleep(800)
console.log(`已点选：${label}`)
process.exit(0)
