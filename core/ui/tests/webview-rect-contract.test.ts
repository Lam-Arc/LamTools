import { describe, expect, it } from 'vitest'
import { webviewBoundsArgs, type WebviewRectInput } from '../src/split/native'

// user:“矩形契约（唯一来源）：入参是布局算出的 contentRect（CSS px），
// 这里只做 CSS px × dpr → 物理像素、整数化、最小 1px”+
// (三档缩放 + 731×500 极端视口逐位断言；任何地方再乘一次 dpr 都会让这组数字对不上)。
describe('webview rect contract (css px → physical px)', () => {
  const rect = { x: 100, y: 60, width: 800, height: 600 }
  const input = (contentRect: WebviewRectInput['contentRect'], visible = true): WebviewRectInput =>
    ({ surfaceId: 'area-1', contentRect, visible })

  it('dpr 1.25 → 物理像素 = round(css × 1.25)', () => {
    expect(webviewBoundsArgs(input(rect), 1.25)).toEqual({
      label: 'area-1', x: 125, y: 75, width: 1000, height: 750, visible: true,
    })
  })

  it('dpr 1.5 → 物理像素 = round(css × 1.5)', () => {
    expect(webviewBoundsArgs(input(rect), 1.5)).toEqual({
      label: 'area-1', x: 150, y: 90, width: 1200, height: 900, visible: true,
    })
  })

  it('dpr 1.85 → 物理像素 = round(css × 1.85)', () => {
    expect(webviewBoundsArgs(input(rect), 1.85)).toEqual({
      label: 'area-1', x: 185, y: 111, width: 1480, height: 1110, visible: true,
    })
  })

  // user:“731×500 极端视口”+(窄到 731、矮到 500 时一步取整都不能丢边，否则最后一列/最后一行会越界 1px)。
  it('731×500 视口在三档 dpr 下都不丢边', () => {
    const narrow = { x: 0, y: 0, width: 731, height: 500 }
    expect(webviewBoundsArgs(input(narrow), 1.25)).toMatchObject({ x: 0, y: 0, width: 914, height: 625 })
    expect(webviewBoundsArgs(input(narrow), 1.5)).toMatchObject({ width: 1097, height: 750 })
    expect(webviewBoundsArgs(input(narrow), 1.85)).toMatchObject({ width: 1352, height: 925 })
  })

  it('宽高至少 1px，非法 dpr 退回 1', () => {
    expect(webviewBoundsArgs(input({ x: 0, y: 0, width: 0.2, height: 0.2 }), 1.25)).toMatchObject({ width: 1, height: 1 })
    expect(webviewBoundsArgs(input({ x: 10, y: 10, width: 100, height: 100 }), 0)).toMatchObject({ x: 10, y: 10, width: 100, height: 100 })
    expect(webviewBoundsArgs(input({ x: 10, y: 10, width: 100, height: 100 }), Number.NaN)).toMatchObject({ x: 10, y: 10 })
  })

  it('visible 与 label 原样透传（判定不在这里做）', () => {
    expect(webviewBoundsArgs(input(rect, false), 1.5)).toMatchObject({ label: 'area-1', visible: false })
  })
})
