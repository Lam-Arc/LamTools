import { afterEach, describe, expect, it, vi } from 'vitest'
import { hostBlockedByOverlay } from '../src/split/browserOverlay'

const rect = (x: number, y: number, width: number, height: number) => ({ x, y, width, height, left: x, top: y, right: x + width, bottom: y + height, toJSON() {} }) as DOMRect

afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })

function element(attributes: Record<string, string>, box: DOMRect, rendered = true) {
  const node = document.createElement('div')
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value)
  vi.spyOn(node, 'getBoundingClientRect').mockReturnValue(box)
  vi.spyOn(node, 'getClientRects').mockReturnValue((rendered ? [box] : []) as unknown as DOMRectList)
  document.body.append(node)
  return node
}

// user:“审查分屏代码，并优化”+(设置页常驻的 listbox 只在真正覆盖浏览器时隐藏网页，不能让它永久空白)。
describe('split browser overlay detection', () => {
  it('ignores listboxes and side cards that do not cover the host', () => {
    const host = element({}, rect(0, 0, 400, 300))
    element({ role: 'listbox' }, rect(600, 0, 100, 100))
    element({ class: 'right-sidebar-card' }, rect(900, 0, 200, 600))
    expect(hostBlockedByOverlay(host)).toBe(false)
  })

  it('blocks the host when a rendered listbox or side card actually overlaps it', () => {
    const host = element({}, rect(0, 0, 400, 300))
    element({ role: 'listbox' }, rect(120, 120, 120, 120))
    expect(hostBlockedByOverlay(host)).toBe(true)
  })

  it('ignores hidden listboxes but always blocks behind a rendered modal backdrop', () => {
    const host = element({}, rect(0, 0, 400, 300))
    element({ role: 'listbox' }, rect(120, 120, 120, 120), false)
    expect(hostBlockedByOverlay(host)).toBe(false)
    element({ 'aria-modal': 'true' }, rect(700, 700, 50, 50))
    expect(hostBlockedByOverlay(host)).toBe(true)
  })
})
