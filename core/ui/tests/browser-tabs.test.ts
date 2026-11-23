import { describe, expect, it } from 'vitest'
import { closeTab, createSplitState, moveTab, openTab, reorderTab, splitPane, type SplitState, type SplitTab } from '../src/workspace/types'

// user:“能开多个标签、拖动排序、关闭重开”+(浏览器标签就是分屏标签：顺序、活动标签与关闭回落都在布局模型里)。
function browserTab(id: string, resource = `https://example.com/${id}`): SplitTab {
  return { id, kind: 'browser', resource, title: id }
}

function workspace(): { state: SplitState; pane: string } {
  const state = createSplitState()
  const pane = splitPane(state, 'main', 'right')!
  return { state, pane }
}

describe('browser tab order and lifecycle', () => {
  it('opens tabs into the pane and makes the newest one active', () => {
    const { state, pane } = workspace()
    openTab(state, pane, browserTab('a'))
    openTab(state, pane, browserTab('b'))
    expect(state.panes[pane].tabs.map(tab => tab.id)).toEqual(['a', 'b'])
    expect(state.panes[pane].activeTab).toBe('b')
  })

  it('reuses an existing tab with the same url instead of duplicating it', () => {
    const { state, pane } = workspace()
    openTab(state, pane, browserTab('a', 'https://example.com/one'))
    openTab(state, pane, browserTab('b', 'https://example.com/one'))
    expect(state.panes[pane].tabs).toHaveLength(1)
    expect(state.panes[pane].activeTab).toBe('a')
  })

  it('reorders within a pane and keeps the active tab', () => {
    const { state, pane } = workspace()
    for (const id of ['a', 'b', 'c']) openTab(state, pane, browserTab(id))
    expect(reorderTab(state, pane, 'c', 0)).toBe(true)
    expect(state.panes[pane].tabs.map(tab => tab.id)).toEqual(['c', 'a', 'b'])
    expect(state.panes[pane].activeTab).toBe('c')
    expect(reorderTab(state, pane, 'a', 2)).toBe(true)
    expect(state.panes[pane].tabs.map(tab => tab.id)).toEqual(['c', 'b', 'a'])
  })

  it('ignores reorder requests for unknown tabs or panes', () => {
    const { state, pane } = workspace()
    openTab(state, pane, browserTab('a'))
    expect(reorderTab(state, pane, 'missing', 0)).toBe(false)
    expect(reorderTab(state, 'missing-pane', 'a', 0)).toBe(false)
  })

  it('moves the active tab to its neighbour when it is closed', () => {
    const { state, pane } = workspace()
    for (const id of ['a', 'b', 'c']) openTab(state, pane, browserTab(id))
    closeTab(state, pane, 'c')
    expect(state.panes[pane].tabs.map(tab => tab.id)).toEqual(['a', 'b'])
    expect(state.panes[pane].activeTab).toBe('b')
  })

  it('moves a tab to another pane without duplicating content', () => {
    const { state, pane } = workspace()
    const other = splitPane(state, pane, 'bottom')!
    openTab(state, pane, browserTab('a'))
    openTab(state, other, browserTab('b'))
    moveTab(state, pane, other, 'a')
    expect(state.panes[other].tabs.map(tab => tab.id)).toEqual(['b', 'a'])
    expect(state.panes[pane]).toBeUndefined()
  })
})
