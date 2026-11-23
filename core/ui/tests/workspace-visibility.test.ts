import { describe, expect, it } from 'vitest'
import { computeWorkspace, type AreaGeometry } from '../src/workspace/compute'
import { createWorkspace } from '../src/workspace/model'
import { browserVisible, webviewRectFor, type BrowserVisibilityInput } from '../src/workspace/visibility'

// user:“网页可见性是一个纯函数；浮层拖动不隐藏网页”+(让位只由会重排布局的手势触发)。

const rect = { x: 0, y: 0, width: 100, height: 100 }
const base: BrowserVisibilityInput = { rect, areaVisible: true, overlayCount: 0, phase: 'idle', floatBehind: false }

describe('browser visibility', () => {
  it('is visible only when the rect is real, the area shows and nothing covers it', () => {
    expect(browserVisible(base)).toBe(true)
    expect(browserVisible({ ...base, areaVisible: false })).toBe(false)
    expect(browserVisible({ ...base, rect: null })).toBe(false)
    expect(browserVisible({ ...base, rect: { x: 0, y: 0, width: 0, height: 100 } })).toBe(false)
    expect(browserVisible({ ...base, overlayCount: 1 })).toBe(false)
    expect(browserVisible({ ...base, floatBehind: true })).toBe(false)
  })

  it('lets layout-rearranging gestures hide the page but keeps floating gestures visible', () => {
    expect(browserVisible({ ...base, phase: 'draggingTab' })).toBe(false)
    expect(browserVisible({ ...base, phase: 'resizingDivider' })).toBe(false)
    expect(browserVisible({ ...base, phase: 'movingArea' })).toBe(false)
    // user:“浮层拖动/缩放不隐藏网页”+(正是这一条让网页能跟手)。
    expect(browserVisible({ ...base, phase: 'floating' })).toBe(true)
  })

  it('derives the webview rect from contentRect with integer + >=1 protection', () => {
    const model = createWorkspace([{ id: 'web', kind: 'browser', title: '浏览器' }], 'web')
    const geometry = computeWorkspace(model, { x: 0, y: 0, width: 1200, height: 800 })
    const area: AreaGeometry = geometry.areas.main
    const webview = webviewRectFor(area, 36)
    expect(webview).toEqual({
      x: Math.round(area.contentRect.x),
      y: Math.round(area.contentRect.y),
      width: Math.max(1, Math.round(area.contentRect.width)),
      height: Math.max(1, Math.round(area.contentRect.height)),
    })
    expect(webview.height).toBe(800 - 36 - 36)
    // 退化矩形也不会拿到 0 或负数。
    const degenerate = webviewRectFor({ ...area, contentRect: { x: 0, y: 0, width: 0.4, height: 0.2 } }, 36)
    expect(degenerate.width).toBeGreaterThanOrEqual(1)
    expect(degenerate.height).toBeGreaterThanOrEqual(1)
  })
})
