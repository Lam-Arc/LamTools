import { describe, expect, it } from 'vitest'
import {
  areasOf,
  createWorkspace,
  normalizeWorkspace,
  placeOf,
  surfaceIdsOf,
  type Area,
  type SplitNode,
  type SurfaceRef,
  type WorkspaceModel,
} from '../src/workspace/model'

// user:“布局只描述区域，不描述内容；一个 Surface 只有一个 Placement”+(模型层只钉结构不变量)。

const refs: SurfaceRef[] = [
  { id: 'agent', kind: 'agent', title: 'Agent' },
  { id: 'web', kind: 'browser', title: '浏览器' },
  { id: 'file', kind: 'file', title: 'a.ts', resource: '/a.ts' },
]

const leaf = (id: string, tabs: string[], role: 'main' | 'aux', active: string | null = tabs[0] ?? null): SplitNode => ({
  kind: 'leaf',
  area: { id, tabs, active, role, axis: 'vertical' },
})

function twoAreas(): WorkspaceModel {
  return normalizeWorkspace({
    ...createWorkspace(refs, 'agent'),
    tree: {
      kind: 'split',
      direction: 'row',
      ratio: .5,
      a: leaf('main', ['agent'], 'main'),
      b: leaf('aux', ['web'], 'aux'),
    },
  })
}

describe('workspace model', () => {
  it('creates one main area holding the seed surface, axis from its kind', () => {
    const workspace = createWorkspace(refs, 'web')
    const areas = areasOf(workspace)
    expect(areas).toHaveLength(1)
    expect(areas[0]).toMatchObject({ id: 'main', role: 'main', tabs: ['web'], active: 'web', axis: 'horizontal' })
    expect(workspace.version).toBe(4)
    expect(workspace.floats).toEqual([])
    expect(workspace.prefs.compact).toBe(false)
  })

  it('lists areas in tree order and surfaces in area order then float order', () => {
    const workspace = normalizeWorkspace({
      ...twoAreas(),
      floats: [
        { id: 'file', rect: { x: 10, y: 10, width: 100, height: 100 }, yieldEnabled: false },
      ],
    })
    expect(areasOf(workspace).map(area => area.id)).toEqual(['main', 'aux'])
    expect(surfaceIdsOf(workspace)).toEqual(['agent', 'web', 'file'])
  })

  it('resolves placements: area first, float second, unknown last', () => {
    const workspace = normalizeWorkspace({
      ...twoAreas(),
      floats: [{ id: 'file', rect: { x: 0, y: 0, width: 10, height: 10 }, yieldEnabled: false }],
    })
    expect(placeOf(workspace, 'agent')).toEqual({ kind: 'area', areaId: 'main' })
    expect(placeOf(workspace, 'file')).toEqual({ kind: 'float' })
    expect(placeOf(workspace, 'ghost')).toBeNull()
  })

  it('dedupes a surface that appears in two areas, keeping the first in tree order', () => {
    const workspace = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      tree: {
        kind: 'split',
        direction: 'row',
        ratio: .5,
        a: leaf('main', ['agent'], 'main'),
        b: leaf('aux', ['agent', 'web'], 'aux'),
      },
    })
    expect(areasOf(workspace).map(area => area.tabs)).toEqual([['agent'], ['web']])
  })

  it('drops a float whose surface is already placed in an area (one placement only)', () => {
    const workspace = normalizeWorkspace({
      ...twoAreas(),
      floats: [
        { id: 'web', rect: { x: 0, y: 0, width: 10, height: 10 }, yieldEnabled: false },
        { id: 'file', rect: { x: 0, y: 0, width: 10, height: 10 }, yieldEnabled: true },
      ],
    })
    expect(workspace.floats.map(box => box.id)).toEqual(['file'])
    expect(workspace.floats[0].yieldEnabled).toBe(true)
  })

  it('collapses an area only when its content was lost, and keeps an explicitly empty area', () => {
    const lost = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      tree: {
        kind: 'split',
        direction: 'row',
        ratio: .5,
        a: leaf('main', ['agent'], 'main'),
        b: leaf('aux', ['gone'], 'aux'),
      },
    })
    expect(areasOf(lost).map(area => area.id)).toEqual(['main'])

    const empty = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      tree: {
        kind: 'split',
        direction: 'row',
        ratio: .5,
        a: leaf('main', ['agent'], 'main'),
        b: leaf('aux', [], 'aux', null),
      },
    })
    expect(areasOf(empty).map(area => area.id)).toEqual(['main', 'aux'])
  })

  it('keeps exactly one main role and repairs active/axis', () => {
    const areaA: Area = { id: 'a', tabs: ['web'], active: 'ghost', role: 'main', axis: 'vertical' }
    const areaB: Area = { id: 'b', tabs: ['agent'], active: 'agent', role: 'main', axis: 'vertical' }
    const workspace = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      tree: { kind: 'split', direction: 'row', ratio: .5, a: { kind: 'leaf', area: areaA }, b: { kind: 'leaf', area: areaB } },
    })
    const areas = areasOf(workspace)
    expect(areas.filter(area => area.role === 'main')).toHaveLength(1)
    expect(areas[0].active).toBe('web')
    expect(areas[0].axis).toBe('horizontal')
    expect(areas[1].active).toBe('agent')
  })


  it('keeps last float rects for known surfaces and drops unknown ones', () => {
    const workspace = normalizeWorkspace({
      ...createWorkspace(refs, 'web'),
      lastFloatRect: {
        web: { x: 10, y: 20, width: 300, height: 200 },
        ghost: { x: 0, y: 0, width: 10, height: 10 },
      },
    })
    expect(workspace.lastFloatRect.web).toEqual({ x: 10, y: 20, width: 300, height: 200 })
    expect(workspace.lastFloatRect.ghost).toBeUndefined()
  })

  it('syncs a floating surface rect into the last-float record', () => {
    const workspace = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      floats: [{ id: 'web', rect: { x: 5, y: 6, width: 300, height: 200 }, yieldEnabled: false }],
      lastFloatRect: { web: { x: 1, y: 1, width: 100, height: 100 } },
    })
    expect(workspace.lastFloatRect.web).toEqual({ x: 5, y: 6, width: 300, height: 200 })
  })
})
