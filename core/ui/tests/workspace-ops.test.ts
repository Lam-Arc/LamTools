import { describe, expect, it } from 'vitest'
import { computeWorkspace } from '../src/workspace/compute'
import { areasOf, createWorkspace, normalizeWorkspace, placeOf, type Area, type SplitNode, type SurfaceRef, type WorkspaceModel } from '../src/workspace/model'
import {
  closeArea,
  cycleFloatFocus,
  defaultFloatSize,
  floatToBack,
  floatToFront,
  moveArea,
  pinFloat,
  resizeSplit,

  setFloatRect,
  setFloatYield,
  splitArea,
  swapAreas,
  unpinArea,
} from '../src/workspace/ops'

// user:“切布局 = 改 Placement；失败给原因、成功给新 model”+(ops 层只钉语义与不变量)。

const refs: SurfaceRef[] = [
  { id: 'agent', kind: 'agent', title: 'Agent' },
  { id: 'web', kind: 'browser', title: '浏览器' },
  { id: 'file', kind: 'file', title: 'a.ts', resource: '/a.ts' },
]

const viewport = { x: 0, y: 0, width: 1200, height: 800 }

function leaf(id: string, tabs: string[], role: 'main' | 'aux'): SplitNode {
  const area: Area = { id, tabs, active: tabs[0] ?? null, role, axis: 'vertical' }
  return { kind: 'leaf', area }
}

function twoAreas(): WorkspaceModel {
  return normalizeWorkspace({
    ...createWorkspace(refs, 'agent'),
    tree: { kind: 'split', direction: 'row', ratio: .5, a: leaf('main', ['agent'], 'main'), b: leaf('aux', ['web'], 'aux') },
  })
}

function withFloat(): WorkspaceModel {
  return normalizeWorkspace({
    ...createWorkspace(refs, 'agent'),
    surfaces: {
      agent: { id: 'agent', kind: 'agent', title: 'Agent' },
      web: { id: 'web', kind: 'browser', title: '浏览器' },
      file: { id: 'file', kind: 'file', title: 'a.ts', resource: '/a.ts' },
    },
    floats: [
      { id: 'web', rect: { x: 760, y: 100, width: 400, height: 260 }, yieldEnabled: false },
      { id: 'file', rect: { x: 100, y: 100, width: 300, height: 200 }, yieldEnabled: true },
    ],
    floatFocus: 'web',
  })
}

describe('workspace ops', () => {
  it('splits an area on any edge and puts the moved surface into the new area', () => {
    const model = createWorkspace(refs, 'agent')
    const moved = splitArea(model, 'main', 'right', 'web')
    expect(moved.ok).toBe(true)
    if (!moved.ok) return
    expect(areasOf(moved.model)).toHaveLength(2)
    const created = areasOf(moved.model).find(area => area.id !== 'main')!
    expect(created.role).toBe('aux')
    expect(created.tabs).toEqual(['web'])
    expect(placeOf(moved.model, 'web')).toEqual({ kind: 'area', areaId: created.id })
  })

  it('reports reasons instead of mutating on impossible ops', () => {
    const model = createWorkspace(refs, 'agent')
    const split = twoAreas()
    expect(splitArea(model, 'ghost', 'right')).toEqual({ ok: false, reason: 'area-not-found' })
    expect(splitArea(model, 'main', 'right', 'ghost')).toEqual({ ok: false, reason: 'surface-not-found' })
    expect(closeArea(model, 'main')).toEqual({ ok: false, reason: 'main-area' })
    expect(swapAreas(model, 'main', 'ghost')).toEqual({ ok: false, reason: 'area-not-found' })
    // 主区可以被当作目标，但不能被搬走；搬去不存在的目标也有各自的原因码。
    expect(moveArea(model, 'main', 'ghost', 'left')).toEqual({ ok: false, reason: 'main-area' })
    expect(moveArea(split, 'aux', 'ghost', 'left')).toEqual({ ok: false, reason: 'target-not-found' })
  })

  it('closes an auxiliary area and lets the sibling fill the workspace', () => {
    const model = twoAreas()
    const closed = closeArea(model, 'aux')
    expect(closed.ok).toBe(true)
    if (!closed.ok) return
    const geometry = computeWorkspace(closed.model, viewport, { gap: 0 })
    expect(Object.keys(geometry.areas)).toEqual(['main'])
    expect(geometry.areas.main.rect).toEqual({ x: 0, y: 0, width: 1200, height: 800 })
  })

  it('resizes a split by path and leaves invalid paths untouched', () => {
    const model = twoAreas()
    const resized = resizeSplit(model, [], .3)
    // 存的是比率；像素由 compute 算，并按最小尺寸夹住（.3 在 1200 宽会让主区低于 420）。
    expect(resized.tree).toMatchObject({ ratio: .3 })
    expect(computeWorkspace(resized, viewport, { gap: 0 }).areas.main.rect.width).toBe(420)
    // 更宽的窗口里 .3 合法：主区 480。
    expect(computeWorkspace(resized, { x: 0, y: 0, width: 1600, height: 800 }, { gap: 0 }).areas.main.rect.width).toBe(480)
    expect(resizeSplit(model, [0], .5)).toEqual(model)
    expect(resizeSplit(model, [], 7).tree).toMatchObject({ ratio: .98 })
  })


  it('swaps the content sets of two areas without touching roles', () => {
    const model = twoAreas()
    const swapped = swapAreas(model, 'main', 'aux')
    expect(swapped.ok).toBe(true)
    if (!swapped.ok) return
    const areas = areasOf(swapped.model)
    expect(areas[0]).toMatchObject({ id: 'main', role: 'main', tabs: ['web'], active: 'web' })
    expect(areas[1]).toMatchObject({ id: 'aux', role: 'aux', tabs: ['agent'], active: 'agent' })
  })

  it('re-docks an area to another edge with zero net change', () => {
    const model = twoAreas()
    const moved = moveArea(model, 'aux', 'main', 'bottom')
    expect(moved.ok).toBe(true)
    if (!moved.ok) return
    expect(areasOf(moved.model)).toHaveLength(2)
    expect(areasOf(moved.model).map(area => area.role).sort()).toEqual(['aux', 'main'])
    const geometry = computeWorkspace(moved.model, viewport, { gap: 0 })
    const entries = Object.values(geometry.areas).map(value => value.rect)
    const sum = entries.reduce((total, rect) => total + rect.width * rect.height, 0)
    expect(sum).toBe(1200 * 800)
    // 上下左右都不重叠：新位置是“目标的下方”，两块等宽。
    expect(entries[0].width).toBe(entries[1].width)
  })

  it('pins a float, returning a preview that equals the landed rect', () => {
    const model = withFloat()
    const pinned = pinFloat(model, 'web', viewport)
    expect(pinned.ok).toBe(true)
    if (!pinned.ok) return
    expect(pinned.model.floats.map(box => box.id)).toEqual(['file'])
    const place = placeOf(pinned.model, 'web')
    expect(place?.kind).toBe('area')
    if (!place || place.kind !== 'area') return
    const geometry = computeWorkspace(pinned.model, viewport)
    expect(geometry.areas[place.areaId].rect).toEqual(pinned.preview)
    expect(pinned.model).not.toHaveProperty('focusAreaId')
  })

  it('refuses to pin when nothing fits, with a readable reason', () => {
    const model = withFloat()
    const tiny = { x: 0, y: 0, width: 100, height: 100 }
    expect(pinFloat(model, 'web', tiny)).toEqual({ ok: false, reason: 'insufficient' })
    expect(pinFloat(model, 'agent', viewport)).toEqual({ ok: false, reason: 'not-a-float' })
  })

  it('unpins an area back to a float with defaultFloatSize, focusing it and closing the emptied area', () => {
    const model = twoAreas()
    const geometry = computeWorkspace(model, viewport)
    const auxRect = geometry.areas.aux.rect
    const expectedSize = defaultFloatSize(auxRect, viewport)
    const unpinned = unpinArea(model, 'aux', viewport)
    expect(unpinned.ok).toBe(true)
    if (!unpinned.ok) return
    const box = unpinned.model.floats[0]
    expect(box.id).toBe('web')
    expect(box.rect.width).toBe(expectedSize.width)
    expect(box.rect.height).toBe(expectedSize.height)
    expect(box.rect.x).toBe(auxRect.x + 24)
    expect(box.rect.y).toBe(auxRect.y + 24)
    expect(unpinned.model.floatFocus).toBe('web')
    expect(areasOf(unpinned.model).map(area => area.id)).toEqual(['main'])
    expect(unpinArea(model, 'ghost', viewport)).toEqual({ ok: false, reason: 'area-not-found' })
  })

  it('reorders floats, keeps focus valid and updates rect/yield', () => {
    const model = withFloat()
    const front = floatToFront(model, 'web')
    expect(front.floats.map(box => box.id)).toEqual(['file', 'web'])
    expect(front.floatFocus).toBe('web')
    const back = floatToBack(model, 'web')
    expect(back.floats.map(box => box.id)).toEqual(['web', 'file'])
    expect(back.floatFocus).toBe('file')
    const cycled = cycleFloatFocus(model, 1)
    expect(cycled.floatFocus).toBe('file')
    expect(cycled.floats[cycled.floats.length - 1].id).toBe('file')
    const rect = setFloatRect(model, 'web', { x: 10, y: 20, width: 200, height: 100 })
    expect(rect.floats.find(box => box.id === 'web')?.rect).toEqual({ x: 10, y: 20, width: 200, height: 100 })
    expect(setFloatYield(model, 'web', true).floats.find(box => box.id === 'web')?.yieldEnabled).toBe(true)
    expect(setFloatYield(model, 'ghost', true)).toBe(model)
  })


  it('unpin restores the float size recorded before pinning', () => {
    const sized = setFloatRect(withFloat(), 'web', { x: 200, y: 120, width: 520, height: 360 })
    const pinned = pinFloat(sized, 'web', viewport)
    expect(pinned.ok).toBe(true)
    if (!pinned.ok) return
    const place = placeOf(pinned.model, 'web')
    if (!place || place.kind !== 'area') throw new Error('float should be docked after pin')
    const unpinned = unpinArea(pinned.model, place.areaId, viewport)
    expect(unpinned.ok).toBe(true)
    if (!unpinned.ok) return
    const box = unpinned.model.floats.find(item => item.id === 'web')!
    expect({ width: box.rect.width, height: box.rect.height }).toEqual({ width: 520, height: 360 })
  })

  it('clamps the restored float into a smaller window', () => {
    const sized = setFloatRect(withFloat(), 'web', { x: 900, y: 600, width: 520, height: 360 })
    const pinned = pinFloat(sized, 'web', viewport)
    expect(pinned.ok).toBe(true)
    if (!pinned.ok) return
    const place = placeOf(pinned.model, 'web')
    if (!place || place.kind !== 'area') throw new Error('float should be docked after pin')
    const small = { x: 0, y: 0, width: 600, height: 400 }
    const unpinned = unpinArea(pinned.model, place.areaId, small)
    expect(unpinned.ok).toBe(true)
    if (!unpinned.ok) return
    const box = unpinned.model.floats.find(item => item.id === 'web')!
    // 尺寸照旧（放得下就不缩），位置被夹进视口。
    expect({ width: box.rect.width, height: box.rect.height }).toEqual({ width: 520, height: 360 })
    expect(box.rect.x).toBeGreaterThanOrEqual(0)
    expect(box.rect.y).toBeGreaterThanOrEqual(0)
    expect(box.rect.x + box.rect.width).toBeLessThanOrEqual(600)
    expect(box.rect.y + box.rect.height).toBeLessThanOrEqual(400)
  })

  it('survives five pin → unpin rounds with the same float size', () => {
    let model = setFloatRect(withFloat(), 'web', { x: 200, y: 120, width: 520, height: 360 })
    let settled = ''
    for (let round = 0; round < 5; round += 1) {
      const pinned = pinFloat(model, 'web', viewport)
      expect(pinned.ok).toBe(true)
      if (!pinned.ok) return
      const place = placeOf(pinned.model, 'web')
      if (!place || place.kind !== 'area') throw new Error('float should be docked after pin')
      const unpinned = unpinArea(pinned.model, place.areaId, viewport)
      expect(unpinned.ok).toBe(true)
      if (!unpinned.ok) return
      model = unpinned.model
      const box = model.floats.find(item => item.id === 'web')!
      expect({ width: box.rect.width, height: box.rect.height }).toEqual({ width: 520, height: 360 })
      if (round === 0) settled = JSON.stringify(model)
      // 树形、z 序与记录都停在同一处：没有逐轮累积。
      expect(JSON.stringify(model)).toBe(settled)
    }
  })

  it('falls back to defaultFloatSize when no float size was ever recorded', () => {
    const model = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      tree: { kind: 'split', direction: 'row', ratio: .5, a: leaf('main', ['agent'], 'main'), b: leaf('aux', ['web'], 'aux') },
    })
    expect(model.lastFloatRect).toEqual({})
    const rect = computeWorkspace(model, viewport).areas.aux.rect
    const expectedSize = defaultFloatSize(rect, viewport)
    const unpinned = unpinArea(model, 'aux', viewport)
    expect(unpinned.ok).toBe(true)
    if (!unpinned.ok) return
    const box = unpinned.model.floats.find(item => item.id === 'web')!
    expect(box.rect.width).toBe(expectedSize.width)
    expect(box.rect.height).toBe(expectedSize.height)
  })

  it('falls back to horizontal split when vertical height is insufficient on default desktop viewport', () => {
    const sized = setFloatRect(withFloat(), 'web', { x: 260, y: 180, width: 597, height: 334 })
    const desktopViewport = { x: 0, y: 0, width: 922, height: 495 }
    const pinned = pinFloat(sized, 'web', desktopViewport)
    expect(pinned.ok).toBe(true)
    if (!pinned.ok) return
    expect(pinned.preview.width).toBeGreaterThanOrEqual(320)
  })

  it('auto-enables compact mode during pinFloat when normal limits barely exceed sidebar-narrowed viewport', () => {
    const sized = setFloatRect(withFloat(), 'web', { x: 120, y: 80, width: 480, height: 340 })
    const sidebarOpenViewport = { x: 0, y: 0, width: 680, height: 500 }
    const pinned = pinFloat(sized, 'web', sidebarOpenViewport)
    expect(pinned.ok).toBe(true)
    if (!pinned.ok) return
    expect(pinned.model.prefs.compact).toBe(true)
    expect(pinned.preview.width).toBeGreaterThanOrEqual(275)
  })

  it('allows pinning on narrow viewports (500x400) and when 2 areas already exist on desktop viewport', () => {
    const narrowSized = setFloatRect(withFloat(), 'web', { x: 60, y: 40, width: 320, height: 240 })
    const narrowPinned = pinFloat(narrowSized, 'web', { x: 0, y: 0, width: 500, height: 400 })
    expect(narrowPinned.ok).toBe(true)
    if (!narrowPinned.ok) return
    expect(narrowPinned.preview.width).toBeGreaterThan(0)
    expect(narrowPinned.preview.height).toBeGreaterThan(0)
    expect(placeOf(narrowPinned.model, 'web')?.kind).toBe('area')

    const withTwoAreas = normalizeWorkspace({
      ...twoAreas(),
      surfaces: {
        ...twoAreas().surfaces,
        note: { id: 'note', kind: 'file', title: 'Notes' },
      },
      floats: [{ id: 'note', rect: { x: 240, y: 120, width: 420, height: 300 }, yieldEnabled: false }],
    })
    const thirdPinned = pinFloat(withTwoAreas, 'note', { x: 0, y: 0, width: 922, height: 495 })
    expect(thirdPinned.ok).toBe(true)
    if (!thirdPinned.ok) return
    expect(areasOf(thirdPinned.model)).toHaveLength(3)
    expect(placeOf(thirdPinned.model, 'note')?.kind).toBe('area')
  })
})
