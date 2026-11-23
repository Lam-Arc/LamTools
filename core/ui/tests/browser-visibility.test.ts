import { describe, expect, it } from 'vitest'
import { hostHasArea, layoutPhaseOfController, phaseHidesBrowser, resolveBrowserBounds, serializeBounds, type BrowserVisibilityInput } from '../src/split/browserVisibility'

// user:“网页不会盖住菜单、浮层”+(方案点名的第一号翻车点：把可见性判定收成一个纯函数，穷举所有组合)。
describe('browser bounds and visibility', () => {
  const host = { x: 100, y: 60, width: 800, height: 600 }
  const base: BrowserVisibilityInput = {
    host,
    paneVisible: true,
    tabActive: true,
    workspaceHidden: false,
    overlayOpen: false,
    resizing: false,
    obscured: false,
  }

  it('shows only when every condition allows it', () => {
    expect(resolveBrowserBounds(base)).toEqual({ x: 100, y: 60, width: 800, height: 600, visible: true })
  })

  it('hides when any single blocking condition is set (exhaustive)', () => {
    const flags = ['paneVisible', 'tabActive', 'workspaceHidden', 'overlayOpen', 'resizing', 'obscured'] as const
    // 6 个开关全组合 = 64 种，只有“全为允许态”的那一种可以显示。
    for (let mask = 0; mask < 64; mask += 1) {
      const input: BrowserVisibilityInput = { ...base }
      let expected = true
      flags.forEach((flag, index) => {
        const on = Boolean(mask & (1 << index))
        if (flag === 'paneVisible' || flag === 'tabActive') {
          input[flag] = on
          expected = expected && on
        } else {
          input[flag] = on
          expected = expected && !on
        }
      })
      expect(resolveBrowserBounds(input).visible, `mask=${mask}`).toBe(expected)
    }
  })

  it('never reports visible without a mounted host area', () => {
    expect(resolveBrowserBounds({ ...base, host: null }).visible).toBe(false)
    expect(resolveBrowserBounds({ ...base, host: { x: 0, y: 0, width: 0, height: 0 } }).visible).toBe(false)
    expect(hostHasArea(null)).toBe(false)
    expect(hostHasArea({ x: 0, y: 0, width: 1, height: 1 })).toBe(true)
  })

  it('keeps a positive size for WebView2 even while hidden', () => {
    const bounds = resolveBrowserBounds({ ...base, host: { x: 0, y: 0, width: 0, height: 0 } })
    expect(bounds.width).toBeGreaterThanOrEqual(1)
    expect(bounds.height).toBeGreaterThanOrEqual(1)
  })

  it('rounds to whole pixels and clamps negative offsets', () => {
    const bounds = resolveBrowserBounds({ ...base, host: { x: -12.4, y: -3.6, width: 800.5, height: 600.4 } })
    expect(bounds).toEqual({ x: 0, y: 0, width: 801, height: 600, visible: true })
  })

  it('serialises for change detection', () => {
    const first = resolveBrowserBounds(base)
    const second = resolveBrowserBounds({ ...base })
    expect(serializeBounds(first)).toBe(serializeBounds(second))
    expect(serializeBounds(first)).not.toBe(serializeBounds({ ...first, visible: false }))
  })
})

// user:“90 种可见性组合逐条断言”+(3 rect × 2 areaVisible × 3 overlayCount × 5 phase)：
// 只有「rect 有效 + Area 可见 + 没有浮层 + 不是三种重排手势」才可见。
describe('browserVisible: 90 组合表驱动', () => {
  const rects: Array<{ width: number; height: number } | null> = [null, { width: 0, height: 100 }, { width: 800, height: 600 }]
  const areaFlags = [true, false]
  const overlayCounts = [0, 1, 3]
  const phases = ['idle', 'draggingTab', 'resizingDivider', 'movingArea', 'floating'] as const
  const reflow = new Set(['draggingTab', 'resizingDivider', 'movingArea'])

  it('穷举 3×2×3×5 = 90 种组合', () => {
    let checked = 0
    for (const rect of rects) {
      for (const areaVisible of areaFlags) {
        for (const overlayCount of overlayCounts) {
          for (const phase of phases) {
            const expected = Boolean(rect) && (rect as { width: number }).width >= 1 && (rect as { height: number }).height >= 1
              && areaVisible && overlayCount === 0 && !reflow.has(phase)
            expect(
              browserVisible({ rect, areaVisible, overlayCount, phase }),
              `rect=${JSON.stringify(rect)} area=${areaVisible} overlay=${overlayCount} phase=${phase}`,
            ).toBe(expected)
            checked += 1
          }
        }
      }
    }
    expect(checked).toBe(90)
  })

  it('关键反例：浮层拖动不隐藏，重排手势才隐藏', () => {
    const ok = { width: 800, height: 600 }
    expect(browserVisible({ rect: ok, areaVisible: true, overlayCount: 0, phase: 'floating' })).toBe(true)
    expect(browserVisible({ rect: ok, areaVisible: true, overlayCount: 0, phase: 'idle' })).toBe(true)
    for (const phase of ['draggingTab', 'resizingDivider', 'movingArea'] as const) {
      expect(browserVisible({ rect: ok, areaVisible: true, overlayCount: 0, phase })).toBe(false)
    }
    expect(browserVisible({ rect: ok, areaVisible: true, overlayCount: 1, phase: 'idle' })).toBe(false)
  })
})

import { browserVisible } from '../src/split/browserVisibility'

// user:“分屏拖动手感不佳，卡顿/不跟手”+
// (控制器拖分隔条时是 `resizingDivider`，浏览器可见性却只认 `resizing`；这里钉住映射，
//  确保拉分隔条时网页让位，而不是每帧追着 IPC 跑)。
describe('controller phase mapping', () => {
  it('maps the divider/moving phases to the phases that make the page yield', () => {
    expect(layoutPhaseOfController('resizingDivider')).toBe('resizingDivider')
    expect(phaseHidesBrowser(layoutPhaseOfController('resizingDivider'))).toBe(true)
    expect(layoutPhaseOfController('movingArea')).toBe('movingArea')
    expect(phaseHidesBrowser(layoutPhaseOfController('movingArea'))).toBe(true)
    expect(layoutPhaseOfController('draggingTab')).toBe('draggingTab')
    expect(phaseHidesBrowser(layoutPhaseOfController('draggingTab'))).toBe(true)
  })

  it('keeps floating and idle phases visible', () => {
    expect(layoutPhaseOfController('floating')).toBe('floating')
    expect(phaseHidesBrowser(layoutPhaseOfController('floating'))).toBe(false)
    expect(layoutPhaseOfController('idle')).toBe('idle')
    expect(layoutPhaseOfController(undefined)).toBe('idle')
    expect(phaseHidesBrowser(layoutPhaseOfController(undefined))).toBe(false)
  })
})
