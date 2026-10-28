import { describe, expect, it } from 'vitest'
import { canFitSplit, canJoinPanes, createSplitState, splitPane, openTab, moveTab, closeTab, closePane, resizeSplit, arrangeLayout, joinPanes, layoutRects, minimumSize, paneIds, restoreSplitState, swapPanes, SPLIT_TAB_BAR_HEIGHT } from '../src/split/layout'

// user:“第一版就支持多个分屏，左右 / 上下自由组合”+(验收递归布局、移动与恢复，不以固定右侧栏代替分屏)。
describe('Split Pane workspace', () => {
  it('keeps an untagged primary area and recursively splits any auxiliary pane', () => {
    const state = createSplitState()
    const right = splitPane(state, 'main', 'right')!
    const below = splitPane(state, right, 'bottom')!
    openTab(state, right, { id: 'library', kind: 'page', title: '资料库', resource: 'library' })
    openTab(state, below, { id: 'settings', kind: 'page', title: '设置', resource: 'settings' })
    expect(state.panes.main).toBeUndefined()
    const rects = layoutRects(state.tree, { x: 0, y: 0, width: 1200, height: 800 })
    expect(rects.panes.main.width).toBeGreaterThan(420)
    expect(rects.panes[right].y).toBe(0)
    expect(rects.panes[below].y).toBeGreaterThan(0)
    expect(rects.panes[right].x).toBe(rects.panes[below].x)
    expect(Object.keys(rects.panes)).toHaveLength(3)
  })
  it('deduplicates content in one pane and moves a live tab without copying its state', () => {
    const state = createSplitState(), a = splitPane(state, 'main', 'right')!, b = splitPane(state, a, 'bottom')!
    const tab = { id: 'file-a', kind: 'editor' as const, resource: '/a.md', title: 'a.md' }
    openTab(state, a, tab); openTab(state, a, { ...tab, id: 'another' })
    expect(state.panes[a].tabs).toHaveLength(1)
    moveTab(state, a, b, tab.id)
    expect(state.panes[a]).toBeUndefined()
    expect(state.panes[b].tabs[0]).toBe(tab)
    expect(state.activePane).toBe(b)
    expect(closeTab(state, b, tab.id)).toBe(true)
    expect(state.tree).toEqual({ type: 'pane', id: 'main' })
  })
  it('cannot close main or move tabs into its titlebar', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!
    openTab(state, right, { id: 'web', kind: 'browser', resource: '', title: '浏览器' })
    closePane(state, 'main'); moveTab(state, right, 'main', 'web')
    expect(state.panes[right].tabs).toHaveLength(1)
    expect(layoutRects(state.tree, { x: 0, y: 0, width: 1200, height: 800 }).panes.main).toBeDefined()
  })
  it('enforces recursive minimum sizes and bounds splitter movement', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!
    splitPane(state, right, 'bottom')
    expect(minimumSize(state.tree)).toEqual({ width: 742, height: 482 })
    const root = state.tree
    if (root.type !== 'split') throw Error('expected split')
    resizeSplit(state.tree, root.id, -20, 1200)
    expect(root.ratio).toBeGreaterThanOrEqual(420 / 1198)
    resizeSplit(state.tree, root.id, 20, 1200)
    expect(root.ratio).toBeLessThanOrEqual(1 - 320 / 1198)
  })
  // user:“拖拽的判定，应该只有中间区域是拖拽判定，偏靠角的那一块应该留给创建分屏的判定”+(分隔线中段才可拖动，角部让给角柄)。
  it('keeps resizing on the middle of a divider and reserves its corners', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!
    const columns = layoutRects(state.tree, { x: 0, y: 0, width: 1200, height: 800 }).dividers[0]
    expect(columns.handle.y).toBeGreaterThan(columns.rect.y + SPLIT_TAB_BAR_HEIGHT)
    expect(columns.handle.y + columns.handle.height).toBeLessThan(columns.rect.y + columns.rect.height - 10)
    expect(columns.handle.width).toBeGreaterThan(columns.rect.width)
    splitPane(state, right, 'bottom')
    const rows = layoutRects(state.tree, { x: 0, y: 0, width: 1200, height: 800 }).dividers.find(divider => divider.direction === 'rows')!
    expect(rows.handle.x).toBeGreaterThan(rows.rect.x + 10)
    expect(rows.handle.x + rows.handle.width).toBeLessThan(rows.rect.x + rows.rect.width - 10)
    expect(rows.handle.height).toBeGreaterThan(rows.rect.height)
  })
  // user:“审查分屏代码，并优化”+(把标签移到已经显示同一内容的屏时合并到原标签，不能出现两份相同内容)。
  it('merges a moved tab into an existing copy instead of duplicating it', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!, below = splitPane(state, right, 'bottom')!
    const first = { id: 'first', kind: 'editor' as const, resource: '/a.md', title: 'a.md' }
    const second = { id: 'second', kind: 'editor' as const, resource: '/a.md', title: 'a.md' }
    openTab(state, right, first); openTab(state, below, second)
    moveTab(state, right, below, first.id)
    expect(state.panes[right]).toBeUndefined()
    expect(state.panes[below].tabs).toHaveLength(1)
    expect(state.panes[below].activeTab).toBe(second.id)
    expect(state.activePane).toBe(below)
  })
  it('keeps the same file as separate tabs when its project scope differs', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!, below = splitPane(state, right, 'bottom')!
    const first = { id: 'first', kind: 'editor' as const, resource: '/a.md', title: 'a.md', root: 'E:/one' }
    const second = { id: 'second', kind: 'editor' as const, resource: '/a.md', title: 'a.md', root: 'E:/two' }
    openTab(state, right, first); openTab(state, below, second)
    moveTab(state, right, below, first.id)
    expect(state.panes[below].tabs.map(t => t.id)).toEqual(['second', 'first'])
    expect(state.panes[below].activeTab).toBe('first')
  })
  // user:“审查分屏代码，并优化”+(连续拆分同一块屏形成的深链也在 24 块屏上限内，重启后不能误判为损坏数据)。
  it('restores a deep chain produced by repeatedly splitting the same pane', () => {
    const state = createSplitState()
    let pane = 'main'
    for (let i = 0; i < 17; i++) pane = splitPane(state, pane, 'right')!
    openTab(state, pane, { id: 'deep', kind: 'editor', resource: '/a.md', title: 'a.md' })
    const restored = restoreSplitState(JSON.stringify(state))
    expect(restored.panes[pane]).toBeDefined()
    expect(paneIds(restored.tree)).toHaveLength(18)
  })
  // user:“该对齐的就全部都去对齐”“我要体验一致化”+(角拖合并与边框交换共用同一套布局动作)。
  it('joins sibling panes into one area and swaps pane contents', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!, below = splitPane(state, right, 'bottom')!
    openTab(state, right, { id: 'a', kind: 'page', title: 'A', resource: 'res-a' })
    openTab(state, below, { id: 'b', kind: 'page', title: 'B', resource: 'res-b' })
    expect(canJoinPanes(state.tree, right, below)).toBe(true)
    expect(canJoinPanes(state.tree, right, 'main')).toBe(false)
    const before = layoutRects(state.tree, { x: 0, y: 0, width: 1200, height: 800 }).panes
    expect(joinPanes(state, right, below)).toBe(true)
    expect(state.panes[right]).toBeUndefined()
    expect(state.panes[below].tabs.map(t => t.id)).toEqual(['b', 'a'])
    const after = layoutRects(state.tree, { x: 0, y: 0, width: 1200, height: 800 }).panes[below]
    expect(after.width).toBe(before[right].width)
    expect(after.height).toBe(before[right].height + before[below].height + 2)
    const extra = splitPane(state, below, 'right')!
    openTab(state, below, { id: 'c', kind: 'page', title: 'C', resource: 'res-c' })
    openTab(state, extra, { id: 'd', kind: 'page', title: 'D', resource: 'res-d' })
    expect(swapPanes(state, below, extra)).toBe(true)
    expect(state.panes[below].tabs.map(t => t.id)).toEqual(['d'])
    expect(state.panes[extra].tabs.map(t => t.id)).toEqual(['b', 'a', 'c'])
  })
  it('preserves every tab when applying layout presets', () => {
    const state = createSplitState()
    for (let i = 0; i < 5; i++) {
      const pane = splitPane(state, 'main', 'right')!
      openTab(state, pane, { id: String(i), kind: 'page', title: String(i), resource: `library-${i}` })
    }
    arrangeLayout(state, 'grid')
    expect(Object.values(state.panes).flatMap(p => p.tabs).map(t => t.id).sort()).toEqual(['0','1','2','3','4'])
    expect(Object.keys(layoutRects(state.tree, { x: 0, y: 0, width: 1600, height: 1000 }).panes)).toHaveLength(4)
  })
  // user:“审查分屏代码，并优化”+(预设并屏时相同内容只保留一个标签，不制造无法定位的重复标签)。
  it('merges duplicate content when a preset collapses panes', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!, below = splitPane(state, right, 'bottom')!
    openTab(state, right, { id: 'first', kind: 'page', title: '库', resource: 'library' })
    openTab(state, below, { id: 'second', kind: 'page', title: '库', resource: 'library' })
    arrangeLayout(state, 'columns')
    expect(state.panes[right].tabs.map(t => t.id)).toEqual(['first'])
    expect(Object.keys(state.panes)).toEqual([right])
  })
  // user:“审查分屏代码，并优化”+(全局页面切换项目后仍定位原标签；资料库等项目相关内容保持各自作用域)。
  it('reuses global pages across projects but keeps project pages separate', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!
    openTab(state, right, { id: 's1', kind: 'page', title: '设置', resource: 'settings', root: 'E:/one' })
    openTab(state, right, { id: 's2', kind: 'page', title: '设置', resource: 'settings', root: 'E:/two' })
    expect(state.panes[right].tabs.map(t => t.id)).toEqual(['s1'])
    openTab(state, right, { id: 'l1', kind: 'page', title: '库', resource: 'library', root: 'E:/one' })
    openTab(state, right, { id: 'l2', kind: 'page', title: '库', resource: 'library', root: 'E:/two' })
    expect(state.panes[right].tabs.map(t => t.id)).toEqual(['s1', 'l1', 'l2'])
  })
  it('borrows spare space from neighboring screens before rejecting a split', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!
    // The right pane is currently narrow, but the full layout can accommodate three columns.
    expect(canFitSplit(state.tree, right, 'right', 1200, 800)).toBe(true)
    expect(canFitSplit(state.tree, right, 'right', 900, 800)).toBe(false)
    expect(canFitSplit(state.tree, right, 'bottom', 900, 800)).toBe(true)
  })
  it('restores validated layouts and safely rejects malformed or excessive trees', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!
    openTab(state, right, { id: 'a', kind: 'editor', title: 'a.md', resource: '/a.md' })
    expect(restoreSplitState(JSON.stringify(state)).panes[right].tabs[0].resource).toBe('/a.md')
    expect(restoreSplitState('{broken').tree).toEqual({ type: 'pane', id: 'main' })
    const invalid = { ...state, tree: { type: 'split', id: 'x', direction: 'columns', ratio: NaN, first: state.tree, second: state.tree } }
    expect(restoreSplitState(JSON.stringify(invalid)).tree).toEqual({ type: 'pane', id: 'main' })
  })
  // user:“审查分屏代码，并优化”+(存储被手改或损坏时整份丢弃，避免错位面板、空标签和数组型状态进入运行期)。
  it('rejects restored panes whose identity, active tab or tab id is malformed', () => {
    const state = createSplitState(), right = splitPane(state, 'main', 'right')!
    openTab(state, right, { id: 'a', kind: 'editor', title: 'a.md', resource: '/a.md' })
    const mismatch = JSON.parse(JSON.stringify(state)) as typeof state
    mismatch.panes[right].id = 'another-pane'
    expect(restoreSplitState(JSON.stringify(mismatch)).tree).toEqual({ type: 'pane', id: 'main' })
    const emptyTabId = JSON.parse(JSON.stringify(state)) as typeof state
    emptyTabId.panes[right].tabs[0].id = ''
    expect(restoreSplitState(JSON.stringify(emptyTabId)).tree).toEqual({ type: 'pane', id: 'main' })
    const badActive = JSON.parse(JSON.stringify(state)) as typeof state
    ;(badActive.panes[right] as unknown as Record<string, unknown>).activeTab = 1
    expect(restoreSplitState(JSON.stringify(badActive)).tree).toEqual({ type: 'pane', id: 'main' })
    expect(restoreSplitState(JSON.stringify({ ...state, panes: [] })).tree).toEqual({ type: 'pane', id: 'main' })
  })
})
