import { describe, expect, it } from 'vitest'
import { checkBrowserRect, containsRect, fitRectToContent, paneContentRect, rectOverflow, toPhysical, type SplitRect } from '../src/split/browserLayout'
import { SPLIT_TAB_BAR_HEIGHT } from '../src/workspace/types'

// user:“落点矩形必须满足不变量：完全落在所属 pane 的内容区内（含 1.5/1.85 缩放、主内容模式、聚焦全屏、浮窗、窄窗口折叠五种情况）”+
// (原生 webview 越界多少就吃掉多少点击：越到页眉则「更多」点不动，越到标题栏则最大化/最小化点不动)。
const TITLEBAR = 44
const WORKSPACE: SplitRect = { x: 46, y: TITLEBAR, width: 1200, height: 760 }
const pane = (patch: Partial<SplitRect> = {}): SplitRect => ({ x: 46, y: TITLEBAR, width: 600, height: 760, ...patch })

function browserIn(paneRect: SplitRect, dpr: number) {
  const content = paneContentRect(paneRect, SPLIT_TAB_BAR_HEIGHT)
  // 浏览器自己的页眉（36px）之下才是网页宿主：宿主再收一次页眉高度。
  const host: SplitRect = { x: content.x, y: content.y + 36, width: content.width, height: content.height - 36 }
  return { content, host, check: checkBrowserRect(host, content, dpr) }
}

describe('浏览器落点不变量：webview ⊆ pane 内容区', () => {
  it('1.5 倍缩放下仍然只在内容区里（且物理像素同样包含）', () => {
    const { content, host, check } = browserIn(pane({ width: 620, height: 700 }), 1.5)
    expect(check.ok).toBe(true)
    expect(check.physicalOk).toBe(true)
    // 内容区从标签栏下面开始，网页从页眉下面开始：两者都不碰标题栏。
    expect(content.y).toBe(TITLEBAR + SPLIT_TAB_BAR_HEIGHT)
    expect(host.y).toBeGreaterThan(TITLEBAR)
    expect(toPhysical(host, 1.5).y).toBeGreaterThan(toPhysical(content, 1.5).y - SPLIT_TAB_BAR_HEIGHT * 1.5 - 1)
  })

  it('1.85 倍缩放（实测过的 dpr）下也不越界', () => {
    const { check, content, host } = browserIn(pane({ width: 1400, height: 900 }), 1.85)
    expect(check.ok).toBe(true)
    expect(check.physicalOk).toBe(true)
    expect(containsRect(toPhysical(content, 1.85), toPhysical(host, 1.85))).toBe(true)
  })

  it('浏览器作为主内容时，落点仍在主槽位内容区里（不含槽位标题栏）', () => {
    // 主槽位：整块主区矩形，自带 36px 标题栏；网页宿主在标题栏之下。
    const mainPane = WORKSPACE
    const { content, host, check } = browserIn(mainPane, 1)
    expect(check.ok).toBe(true)
    expect(host.y - WORKSPACE.y).toBeGreaterThanOrEqual(SPLIT_TAB_BAR_HEIGHT + 36)
  })

  it('聚焦全屏：内容铺满，但底部窄条让开（网页不与输入框相交）', () => {
    const content = paneContentRect(WORKSPACE, SPLIT_TAB_BAR_HEIGHT)
    const composerTop = WORKSPACE.y + WORKSPACE.height - 120
    const host: SplitRect = { x: content.x, y: content.y + 36, width: content.width, height: composerTop - (content.y + 36) }
    const check = checkBrowserRect(host, content, 1)
    expect(check.ok).toBe(true)
    expect(host.y + host.height).toBeLessThanOrEqual(composerTop)
  })

  it('浮窗：网页矩形在内边距里，四边都不出框', () => {
    const frame: SplitRect = { x: 300, y: 200, width: 520, height: 400 }
    const inset = 8
    const host: SplitRect = { x: frame.x + inset, y: frame.y + inset * 2, width: frame.width - inset * 2, height: frame.height - inset * 3 }
    const content: SplitRect = { x: frame.x, y: frame.y, width: frame.width, height: frame.height }
    expect(checkBrowserRect(host, content, 1.5).ok).toBe(true)
  })

  it('窄窗口折叠：主区占满、辅助屏收成 32px 折叠条，网页不得伸进折叠条与标题栏', () => {
    const workspace: SplitRect = { x: 46, y: TITLEBAR, width: 520, height: 700 }
    const strip = 32
    const mainPane: SplitRect = { x: workspace.x, y: workspace.y, width: workspace.width - strip, height: workspace.height }
    const { content, host, check } = browserIn(mainPane, 1.5)
    expect(check.ok).toBe(true)
    expect(host.x + host.width).toBeLessThanOrEqual(workspace.x + workspace.width - strip + 0.5)
    expect(host.y).toBeGreaterThanOrEqual(TITLEBAR + SPLIT_TAB_BAR_HEIGHT)
  })
})

describe('越界会被求交收住（不是「再减一点」）', () => {
  it('宿主机被上游放大到整块工作区时，交集只剩内容区', () => {
    const content = paneContentRect(pane(), SPLIT_TAB_BAR_HEIGHT)
    const runaway: SplitRect = { x: 0, y: 0, width: 1280, height: 900 }
    const fitted = fitRectToContent(runaway, content)
    expect(fitted?.clamped).toBe(true)
    expect(fitted?.rect).toEqual(content)
  })

  it('与内容区完全不相交时退化成不可见（0 尺寸交给 resolveBrowserBounds 判 visible=false）', () => {
    const content = paneContentRect(pane(), SPLIT_TAB_BAR_HEIGHT)
    const fitted = fitRectToContent({ x: 0, y: 0, width: 10, height: 10 }, content)
    expect(fitted?.clamped).toBe(true)
    expect(fitted?.rect.width).toBe(0)
  })

  it('越界量能报出是往哪一边越的（日志用）', () => {
    const content = paneContentRect(pane(), SPLIT_TAB_BAR_HEIGHT)
    const overflow = rectOverflow(content, { x: content.x, y: 0, width: content.width, height: content.y + content.height + 40 })
    expect(overflow.top).toBe(content.y)
    expect(overflow.bottom).toBeGreaterThan(0)
    expect(overflow.left).toBe(0)
    expect(overflow.right).toBe(0)
  })
})

// user:“落点不变量：clampToHost 越界即求交并报 overflow；assertInsideHost 只判定不修改”+
// (两条一起用：诊断打日志、单测兜住「网页必须落在 pane 内容区内」)。
describe('clampToHost / assertInsideHost', () => {
  const host = { x: 0, y: 60, width: 800, height: 600 }

  it('完全在内：原样返回、overflow=null', () => {
    const inside = { x: 10, y: 70, width: 100, height: 100 }
    expect(clampToHost(inside, host)).toEqual({ rect: inside, overflow: null })
    expect(assertInsideHost(inside, host)).toBe(true)
  })

  it('越界：求交并给出四边超出量', () => {
    const outside = { x: 700, y: 600, width: 200, height: 100 }
    const result = clampToHost(outside, host)
    expect(result.rect).toEqual({ x: 700, y: 600, width: 100, height: 60 })
    expect(result.overflow).toEqual({ top: 0, left: 0, right: 100, bottom: 40 })
    expect(assertInsideHost(outside, host)).toBe(false)
  })

  it('交集为空：退化成 0×0（上层判成不可见）', () => {
    const disjoint = { x: 900, y: 700, width: 50, height: 50 }
    expect(clampToHost(disjoint, host).rect).toMatchObject({ width: 0, height: 0 })
    expect(assertInsideHost(disjoint, host)).toBe(false)
  })
})

import { assertInsideHost, clampToHost } from '../src/split/browserLayout'
