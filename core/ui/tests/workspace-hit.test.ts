import { describe, expect, it } from 'vitest'
import { computeWorkspace } from '../src/workspace/compute'
import { areasOf, createWorkspace, type Rect } from '../src/workspace/model'
import { splitArea } from '../src/workspace/ops'
import { dropEdgeFor, hitWorkspace, snapRatio } from '../src/workspace/hit'

// user:“角柄 > 交叉点 > 边缘热区 > 标签栏 > 内容区；拖标签时标签栏优先”+(命中只吃几何，不碰 DOM)。

const viewport: Rect = { x: 0, y: 0, width: 1200, height: 800 }

function twoAreas() {
  const base = createWorkspace([
    { id: 'agent', kind: 'agent', title: 'Agent' },
    { id: 'web', kind: 'browser', title: '浏览器' },
  ], 'agent')
  const result = splitArea(base, 'main', 'right', 'web')
  expect(result.ok).toBe(true)
  if (!result.ok) throw new Error('split failed')
  const geometry = computeWorkspace(result.model, viewport)
  const aux = areasOf(result.model).find(area => area.id !== 'main')!
  return { model: result.model, geometry, auxId: aux.id }
}

describe('workspace hit zones', () => {
  it('prioritises corners, then the divider, then edges and content', () => {
    const { model, geometry } = twoAreas()
    expect(hitWorkspace(geometry, model, { x: 5, y: 5 })).toMatchObject({ kind: 'corner', areaId: 'main', corner: 'nw' })
    expect(hitWorkspace(geometry, model, { x: 600, y: 400 })).toMatchObject({ kind: 'divider', path: [], direction: 'row' })
    expect(hitWorkspace(geometry, model, { x: 10, y: 400 })).toMatchObject({ kind: 'edge', areaId: 'main', edge: 'left' })
    expect(hitWorkspace(geometry, model, { x: 700, y: 500 })).toMatchObject({ kind: 'content', areaId: areasOf(model)[1].id })
    expect(hitWorkspace(geometry, model, { x: 2000, y: 2000 })).toEqual({ kind: 'none' })
  })

  it('marks the top strip of a horizontal area as its tab bar', () => {
    const { model, geometry, auxId } = twoAreas()
    // 横向（Browser）：页眉 36 之后、内容区之前的这一条就是标签栏。
    expect(hitWorkspace(geometry, model, { x: 700, y: 50 })).toEqual({ kind: 'tabbar', areaId: auxId })
    // 纵向（Agent）：标签栏在左侧侧栏，默认优先级下边缘热区先命中。
    expect(hitWorkspace(geometry, model, { x: 20, y: 400 })).toMatchObject({ kind: 'edge', areaId: 'main' })
    expect(hitWorkspace(geometry, model, { x: 20, y: 400 }, { priority: 'tabbar-first' })).toEqual({ kind: 'tabbar', areaId: 'main' })
  })

  it('prefers the inner divider in a T-shaped layout', () => {
    const { model, geometry, auxId } = twoAreas()
    const nested = splitArea(model, auxId, 'bottom')
    expect(nested.ok).toBe(true)
    if (!nested.ok) return
    const next = computeWorkspace(nested.model, viewport)
    expect(hitWorkspace(next, nested.model, { x: 700, y: 400 })).toMatchObject({ kind: 'divider', path: [1], direction: 'column' })
  })

  it('snaps ratios to the fixed stops and can be turned off', () => {
    expect(snapRatio(.26)).toBe(.25)
    expect(snapRatio(.74)).toBe(.75)
    expect(snapRatio(.5)).toBe(.5)
    expect(snapRatio(.3)).toBe(.3)
    expect(snapRatio(.26, { snap: false })).toBe(.26)
    expect(snapRatio(.6, { stops: [.6] })).toBe(.6)
    expect(snapRatio(1.4)).toBe(1)
    expect(snapRatio(Number.NaN)).toBe(.5)
  })

  it('picks the nearest edge for a drop target, or the middle', () => {
    const rect: Rect = { x: 0, y: 0, width: 100, height: 100 }
    expect(dropEdgeFor({ x: 5, y: 50 }, rect)).toBe('left')
    expect(dropEdgeFor({ x: 95, y: 50 }, rect)).toBe('right')
    expect(dropEdgeFor({ x: 50, y: 5 }, rect)).toBe('top')
    expect(dropEdgeFor({ x: 50, y: 95 }, rect)).toBe('bottom')
    expect(dropEdgeFor({ x: 50, y: 50 }, rect)).toBe('center')
    expect(dropEdgeFor({ x: -5, y: 50 }, rect)).toBe('center')
  })
})
