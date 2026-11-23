import { describe, expect, it } from 'vitest'
import { areasOf, createWorkspace, normalizeWorkspace, placeOf, type Area, type SplitNode, type SurfaceRef, type WorkspaceModel } from '../src/workspace/model'
import { addTab, closeTab, moveTab, reorderTab, selectTab } from '../src/workspace/tabs'

// user:“标签集合：add/close/reorder/move/select；空区自动收拢”+(标签层只改位置，不销毁内容)。

const refs: SurfaceRef[] = [
  { id: 'agent', kind: 'agent', title: 'Agent' },
  { id: 'web', kind: 'browser', title: '浏览器' },
  { id: 'file', kind: 'file', title: 'a.ts', resource: '/a.ts' },
  { id: 'doc', kind: 'preview', title: 'b.md', resource: '/b.md' },
]

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

describe('workspace tabs', () => {
  it('adds a tab at the end, keeping the current active one', () => {
    const model = createWorkspace(refs, 'agent')
    const next = addTab(model, 'main', refs[1])
    expect(areasOf(next)[0].tabs).toEqual(['agent', 'web'])
    expect(areasOf(next)[0].active).toBe('agent')
    expect(next.surfaces.web).toMatchObject({ id: 'web', kind: 'browser' })
  })

  it('inserts at an explicit index and makes the first tab active in an empty area', () => {
    const model = createWorkspace(refs, 'agent')
    const withWeb = addTab(model, 'main', refs[1], 0)
    expect(areasOf(withWeb)[0].tabs).toEqual(['web', 'agent'])

    const empty = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      tree: { kind: 'split', direction: 'row', ratio: .5, a: leaf('main', ['agent'], 'main'), b: leaf('aux', [], 'aux') },
    })
    const filled = addTab(empty, 'aux', refs[3])
    const aux = areasOf(filled).find(area => area.id === 'aux')!
    expect(aux).toMatchObject({ tabs: ['doc'], active: 'doc' })
  })

  it('takes a surface out of a float when adding it to an area (one placement)', () => {
    const floating = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      floats: [{ id: 'web', rect: { x: 0, y: 0, width: 100, height: 100 }, yieldEnabled: false }],
      floatFocus: 'web',
    })
    const next = addTab(floating, 'main', refs[1])
    expect(next.floats).toEqual([])
    expect(next.floatFocus).toBeNull()
    expect(placeOf(next, 'web')).toEqual({ kind: 'area', areaId: 'main' })
  })

  it('closes a tab and collapses the emptied auxiliary area', () => {
    const model = twoAreas()
    const next = closeTab(model, 'aux', 'web')
    expect(areasOf(next).map(area => area.id)).toEqual(['main'])
    expect(next.surfaces.web).toBeDefined()
  })

  it('keeps the last area alive but empty when its final tab closes', () => {
    const model = createWorkspace(refs, 'agent')
    const next = closeTab(model, 'main', 'agent')
    const areas = areasOf(next)
    expect(areas).toHaveLength(1)
    expect(areas[0]).toMatchObject({ id: 'main', tabs: [], active: null })
  })

  it('moves a tab across areas, collapsing the emptied source', () => {
    const model = twoAreas()
    const next = moveTab(model, { areaId: 'main', index: 0 }, { areaId: 'aux', index: 1 })
    expect(areasOf(next).map(area => area.id)).toEqual(['aux'])
    expect(areasOf(next)[0].tabs).toEqual(['web', 'agent'])
    expect(areasOf(next)[0].active).toBe('agent')
  })

  it('treats a same-area move as a reorder', () => {
    const model = addTab(createWorkspace(refs, 'agent'), 'main', refs[1])
    const next = moveTab(model, { areaId: 'main', index: 1 }, { areaId: 'main', index: 0 })
    expect(areasOf(next)[0].tabs).toEqual(['web', 'agent'])
  })

  it('selects an existing tab and ignores unknown ones', () => {
    const model = addTab(createWorkspace(refs, 'agent'), 'main', refs[1])
    const next = selectTab(model, 'main', 'web')
    expect(areasOf(next)[0].active).toBe('web')
    expect(selectTab(model, 'main', 'ghost')).toBe(model)
    expect(selectTab(model, 'ghost', 'web')).toBe(model)
  })

  it('reorders within an area and clamps invalid indices', () => {
    const model = addTab(addTab(createWorkspace(refs, 'agent'), 'main', refs[1]), 'main', refs[2])
    const next = reorderTab(model, 'main', 2, 0)
    expect(areasOf(next)[0].tabs).toEqual(['file', 'agent', 'web'])
    expect(areasOf(reorderTab(model, 'main', 99, 0))[0].tabs).toEqual(['agent', 'web', 'file'])
    expect(reorderTab(model, 'ghost', 0, 1)).toBe(model)
  })
})
