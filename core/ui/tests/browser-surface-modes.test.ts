import { describe, expect, it } from 'vitest'
import {
  clampFloatFrame,
  clampFrameTopLimit,
  composerInsetFromTop,
  cycleSurface,
  defaultFloatFrame,
  exclusiveSurfaceOwners,
  FLOAT_COMPOSER_RESERVE,
  FLOAT_FRAME_INSET,
  FLOAT_MIN_HEIGHT,
  FLOAT_MIN_WIDTH,
  floatFrameFits,
  focusStripHeight,
  focusStripRect,
  initialSurface,
  moveFloatFrame,
  normalizeZoom,
  resizeFloatFrame,
  zoomPercent,
} from '../src/workspace/surface'
import { resolveBrowserBounds } from '../src/split/browserVisibility'
import { createSplitState, restoreSplitState } from '../src/workspace/types'

// user:“分屏是为了便于交互，如果有什么其他的你认为在 Sunday 中可以便于交互的方式，也可以自行设计”
// (形态集合与每个形态的矩形都是纯函数：这里穷举边界值，真机上只需要确认“看起来对”)。
describe('content surface modes', () => {
  const viewport = { width: 1440, height: 900 }

  it('starts in split and cycles through the three writable modes', () => {
    expect(initialSurface()).toBe('split')
    expect(cycleSurface('split')).toBe('focus')
    expect(cycleSurface('focus')).toBe('float')
    expect(cycleSurface('float')).toBe('split')
  })

  it('only lets one piece of content leave the split grid', () => {
    const tabs = [
      { id: 'a', surface: 'split' as const },
      { id: 'b', surface: 'focus' as const },
      { id: 'c', surface: 'float' as const },
    ]
    // user:“浮层不参与矩形分屏、可多开”+(断言更新理由：浮层之间不再互斥——新开一个浮层不踢掉别的浮层，
    //  只有“聚焦全屏”这种铺满整块的形态仍然独占；浮层共存时的先后由 state.floatOrder 决定)。
    // 聚焦与悬浮之间：留下聚焦，悬浮不再被它复位（两者可以同时存在）。
    expect(exclusiveSurfaceOwners(tabs, 'b')).toEqual([])
    // 留下悬浮：唯一该复位的仍然是那份聚焦。
    expect(exclusiveSurfaceOwners(tabs, 'c')).toEqual(['b'])
    expect(exclusiveSurfaceOwners(tabs, 'a')).toEqual(['b'])
    expect(exclusiveSurfaceOwners([{ id: 'a' }], 'a')).toEqual([])
  })
})

describe('float window frames', () => {
  const viewport = { width: 1440, height: 900 }

  it('defaults to a bottom-right window that leaves the composer alone', () => {
    const frame = defaultFloatFrame(viewport)
    expect(floatFrameFits(frame)).toBe(true)
    // 右下角落点：右边与底边都留了边距
    expect(frame.x + frame.width).toBe(viewport.width - 12)
    expect(frame.y + frame.height).toBe(viewport.height - 12 - FLOAT_COMPOSER_RESERVE)
    // 内缩一圈之后网页还有地方
    expect(frame.width - FLOAT_FRAME_INSET * 2).toBeGreaterThan(0)
    expect(frame.height - FLOAT_FRAME_INSET * 2).toBeGreaterThan(0)
  })

  it('never lets the frame escape the viewport or shrink below its minimum', () => {
    const clamped = clampFloatFrame({ x: -500, y: -500, width: 10, height: 10 }, viewport)
    expect(clamped.x).toBe(0)
    expect(clamped.y).toBe(0)
    expect(clamped.width).toBe(FLOAT_MIN_WIDTH)
    expect(clamped.height).toBe(FLOAT_MIN_HEIGHT)

    const farRight = clampFloatFrame({ x: 99999, y: 99999, width: 400, height: 300 }, viewport)
    expect(farRight.x).toBe(viewport.width - 400)
    expect(farRight.y).toBe(viewport.height - 300)
  })

  it('degrades instead of collapsing when the viewport is smaller than the minimum', () => {
    // 视口比最小窗还小：宁可占满视口，也不留下一条压成 0 的缝
    const tiny = clampFloatFrame({ x: 0, y: 0, width: 600, height: 600 }, { width: 300, height: 180 })
    expect(tiny.width).toBe(300)
    expect(tiny.height).toBe(180)
    expect(floatFrameFits(tiny)).toBe(false)
  })

  it('moves by the pointer delta and keeps the anchor on resize', () => {
    const frame = { x: 100, y: 100, width: 500, height: 400 }
    expect(moveFloatFrame(frame, { dx: 40, dy: -30 }, viewport)).toEqual({ x: 140, y: 70, width: 500, height: 400 })
    // 拖动同样被夹住：冲到屏幕外会被拉回来，不会出现“点不到”
    expect(moveFloatFrame(frame, { dx: 99999, dy: 0 }, viewport).x).toBe(viewport.width - 500)

    const resized = resizeFloatFrame(frame, { dx: 60, dy: 50 }, viewport)
    expect(resized).toEqual({ x: 100, y: 100, width: 560, height: 450 })
    // 缩到最小值以下会停在最小值
    expect(resizeFloatFrame(frame, { dx: -9999, dy: -9999 }, viewport)).toEqual({ x: 100, y: 100, width: FLOAT_MIN_WIDTH, height: FLOAT_MIN_HEIGHT })
  })

  it('keeps the page clear of the composer', () => {
    // 输入框上沿在 760：浮窗底部必须收在这条线以上
    const frame = { x: 100, y: 400, width: 600, height: 500 }
    const clamped = clampFrameTopLimit(frame, 760, 8)
    expect(clamped.y + clamped.height).toBe(752)
    expect(clamped.width).toBe(600)
    // 没有限制（=0）时原样返回
    expect(clampFrameTopLimit(frame, 0)).toBe(frame)
    // 本来就没压到就不动
    const above = { x: 0, y: 0, width: 300, height: 300 }
    expect(clampFrameTopLimit(above, 760)).toBe(above)
  })
})

describe('focus full screen strip', () => {
  it('sizes the conversation strip from the real composer top', () => {
    // 输入框顶部在 780，内容区底边 900 → 输入框占 120；窄条至少要装下它 + 留白
    const inset = composerInsetFromTop(780, 900)
    expect(inset).toBe(120)
    const strip = focusStripHeight(900, inset)
    expect(strip).toBeGreaterThanOrEqual(inset)
    expect(strip).toBe(120 + 32)
  })

  it('always keeps most of the window for content', () => {
    // 即使输入框被撑得很高，窄条也不超过六成
    const strip = focusStripHeight(900, 800)
    expect(strip).toBe(Math.round(900 * 0.6))
    expect(strip).toBeLessThan(900)
  })

  it('grows the strip when the user expands the chat', () => {
    const collapsed = focusStripHeight(1000, 120, false)
    const expanded = focusStripHeight(1000, 120, true)
    expect(expanded).toBeGreaterThan(collapsed)
    expect(expanded).toBe(400)
  })

  it('falls back to a usable strip when the composer cannot be measured', () => {
    // 量不到输入框时按常数兜底，而不是算成 0（0 就等于把聊天藏了）
    expect(composerInsetFromTop(0, 900)).toBe(0)
    expect(composerInsetFromTop(780, 0)).toBe(0)
    expect(focusStripHeight(900, 0)).toBe(96)
    expect(focusStripHeight(0, 120)).toBe(0)
  })

  it('places content above the strip and the strip at the bottom edge', () => {
    const rect = focusStripRect({ width: 1440, height: 900 }, 120, false)
    expect(rect).toEqual({ x: 0, y: 900 - 152, width: 1440, height: 152 })
    // 内容与窄条不重叠：内容高度 = 工作区高度 - 窄条高度
    expect(900 - rect.height).toBe(748)
  })
})

describe('page zoom is remembered apart from the pane ratio', () => {
  it('clamps to the same range as browser_zoom and rejects garbage', () => {
    expect(normalizeZoom(1.5)).toBe(1.5)
    expect(normalizeZoom(1.2345)).toBe(1.23)
    expect(normalizeZoom(0.01)).toBe(0.25)
    expect(normalizeZoom(99)).toBe(5)
    expect(normalizeZoom(Number.NaN)).toBe(1)
    expect(normalizeZoom(undefined)).toBe(1)
    expect(normalizeZoom('1.25')).toBe(1.25)
  })

  it('prints the reading shown on the toolbar', () => {
    expect(zoomPercent(1)).toBe('100%')
    expect(zoomPercent(1.1)).toBe('110%')
    expect(zoomPercent(0.25)).toBe('25%')
    expect(zoomPercent(Number.NaN)).toBe('100%')
  })
})

describe('suppressed page (float window sent behind)', () => {
  const base = {
    host: { x: 100, y: 60, width: 800, height: 600 },
    paneVisible: true,
    tabActive: true,
    workspaceHidden: false,
    overlayOpen: false,
    obscured: false,
  }

  it('hides the page without touching its rectangle', () => {
    const shown = resolveBrowserBounds(base)
    const hidden = resolveBrowserBounds({ ...base, suppressed: true })
    expect(hidden.visible).toBe(false)
    // 置底只是“先让开”，矩形必须原地保留，否则再提回来会跳
    expect({ ...hidden, visible: true }).toEqual(shown)
  })
})

describe('surface state across a restore', () => {
  it('restores the mode together with zoom and the float frame, and normalises what cannot be shown', () => {
    const state = createSplitState()
    state.panes.p1 = {
      id: 'p1',
      activeTab: 't1',
      tabs: [{
        id: 't1', kind: 'browser', title: '示例', resource: 'https://example.com',
        surface: 'focus', surfaceExpanded: true,
        surfaceFrame: { x: 40, y: 50, width: 520, height: 400 },
        zoom: 1.25,
      }],
    }
    state.tree = { type: 'split', id: 's1', direction: 'columns', ratio: .6, first: { type: 'pane', id: 'main' }, second: { type: 'pane', id: 'p1' } }

    const restored = restoreSplitState(JSON.stringify(state))
    const tab = restored.panes.p1.tabs[0]
    // user:“布局保存与恢复：每个 surface 的形态一起进存档”+
    // (P0 期的旧断言要求形态一律回到分屏——那时形态只是“这一次的界面状态”。
    //  P1-3 明确要求形态随布局恢复，所以这里改成“真的恢复”：聚焦仍然留给真有网页的浏览器标签，
    //  恢复前由 normalizeStoredTab 判一次“摆不摆得出来”，判不出来的才会回落成 split)。
    expect(tab.surface).toBe('focus')
    // 真正要记住的是缩放与浮窗位置，它们与形态互不牵连
    expect(tab.zoom).toBe(1.25)
    expect(tab.surfaceFrame).toEqual({ x: 40, y: 50, width: 520, height: 400 })
    // 分屏比例也还在
    expect(restored.tree).toMatchObject({ type: 'split', ratio: .6 })
  })

  it('falls back to split when the stored mode cannot be shown by that content', () => {
    // 编辑器没有网页可搬：存档里写着的“聚焦/浮层”一律回落成分屏，
    // 而不是恢复成一个点了没反应的形态。
    const state = createSplitState()
    state.panes.p1 = {
      id: 'p1',
      activeTab: 't1',
      tabs: [{ id: 't1', kind: 'editor', title: 'a.md', resource: '/a.md', surface: 'float', surfaceExpanded: true }],
    }
    state.tree = { type: 'split', id: 's1', direction: 'columns', ratio: .5, first: { type: 'pane', id: 'main' }, second: { type: 'pane', id: 'p1' } }

    const tab = restoreSplitState(JSON.stringify(state)).panes.p1.tabs[0]
    expect(tab.surface).toBe('split')
    expect(tab.surfaceExpanded).toBe(false)
  })

  it('drops a corrupt float frame instead of handing it to the layout', () => {
    const state = createSplitState()
    state.panes.p1 = {
      id: 'p1',
      activeTab: 't1',
      tabs: [{ id: 't1', kind: 'browser', title: 'x', resource: 'https://example.com', surfaceFrame: { x: 0, y: 0, width: Number.NaN, height: 10 } }],
    }
    state.tree = { type: 'split', id: 's1', direction: 'columns', ratio: .5, first: { type: 'pane', id: 'main' }, second: { type: 'pane', id: 'p1' } }

    const restored = restoreSplitState(JSON.stringify(state))
    expect(restored.panes.p1.tabs[0].surfaceFrame).toBeUndefined()
  })

  it('normalises a stored zoom that is out of range', () => {
    const state = createSplitState()
    state.panes.p1 = { id: 'p1', activeTab: 't1', tabs: [{ id: 't1', kind: 'browser', title: 'x', resource: 'https://example.com', zoom: 99 }] }
    state.tree = { type: 'split', id: 's1', direction: 'columns', ratio: .5, first: { type: 'pane', id: 'main' }, second: { type: 'pane', id: 'p1' } }

    expect(restoreSplitState(JSON.stringify(state)).panes.p1.tabs[0].zoom).toBe(5)
  })
})
