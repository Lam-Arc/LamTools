import { describe, expect, it } from 'vitest'
import { areasOf, createWorkspace, type SurfaceRef } from '../src/workspace/model'
import {
  migrateLegacySplitState,
  parseWorkspace,
  serializeWorkspace,
  WORKSPACE_STORAGE_KEY,
} from '../src/workspace/persist'

// user:“v1–v3 迁移；坏档回 fallback；单个坏 surface/浮层只丢自己”+(持久化层只认结构，不猜内容)。

const refs: SurfaceRef[] = [
  { id: 'agent', kind: 'agent', title: 'Agent' },
  { id: 'web', kind: 'browser', title: '浏览器' },
]

const fallback = createWorkspace(refs, 'agent')

describe('workspace persist', () => {
  it('round-trips a v4 model', () => {
    const model = createWorkspace(refs, 'web')
    const raw = serializeWorkspace(model)
    expect(WORKSPACE_STORAGE_KEY).toBe('lamtools.workspace.v4')
    const parsed = parseWorkspace(raw, fallback)
    expect(parsed.migrated).toBe(false)
    expect(parsed.dropped).toBe(0)
    expect(parsed.model).toEqual(model)
  })

  it('falls back on bad JSON, unknown versions and unusable trees', () => {
    expect(parseWorkspace(null, fallback).model).toBe(fallback)
    expect(parseWorkspace('not json', fallback)).toEqual({ model: fallback, migrated: false, dropped: 0 })
    expect(parseWorkspace(JSON.stringify({ version: 99 }), fallback).model).toBe(fallback)
    expect(parseWorkspace(JSON.stringify({ version: 4, tree: null }), fallback).model).toBe(fallback)
  })

  it('migrates a v1 archive (compact at top level, pane tree)', () => {
    const legacy = {
      version: 1,
      tree: { type: 'split', id: 'root', direction: 'columns', ratio: .6, first: { type: 'pane', id: 'main' }, second: { type: 'pane', id: 'aux' } },
      panes: { aux: { id: 'aux', tabs: [{ id: 'web', kind: 'browser', title: '浏览器', resource: 'https://example.com' }], activeTab: 'web' } },
      compact: true,
    }
    const migrated = migrateLegacySplitState(legacy)
    expect(migrated).not.toBeNull()
    if (!migrated) return
    expect(migrated.model.version).toBe(4)
    expect(migrated.model.prefs.compact).toBe(true)
    expect(areasOf(migrated.model).map(area => area.id)).toEqual(['main', 'aux'])
    expect(migrated.model.surfaces.web).toMatchObject({ kind: 'browser', resource: 'https://example.com' })
    expect(migrated.dropped).toBe(0)
  })

  it('migrates a v2 archive with mainTab into the main area active tab', () => {
    const legacy = {
      version: 2,
      tree: { type: 'split', id: 's1', direction: 'rows', ratio: .4, first: { type: 'pane', id: 'main' }, second: { type: 'pane', id: 'aux' } },
      panes: { aux: { id: 'aux', tabs: [{ id: 'web', kind: 'browser', title: '浏览器' }], activeTab: 'web' } },
      mainTab: { id: 'file', kind: 'editor', title: 'a.ts', resource: '/a.ts' },
      prefs: { compact: false },
    }
    const migrated = migrateLegacySplitState(legacy)
    expect(migrated).not.toBeNull()
    if (!migrated) return
    const main = areasOf(migrated.model).find(area => area.id === 'main')!
    expect(main.tabs).toEqual(['file'])
    expect(main.active).toBe('file')
    expect(migrated.model.surfaces.file).toMatchObject({ kind: 'file', resource: '/a.ts' })
    expect(migrated.model.tree).toMatchObject({ kind: 'split', direction: 'column', ratio: .4 })
  })

  it('migrates v3 floats with their frames and order', () => {
    const legacy = {
      version: 3,
      tree: { type: 'pane', id: 'main' },
      panes: { aux: { id: 'aux', tabs: [{ id: 'web', kind: 'browser', title: '浏览器' }], activeTab: 'web' } },
      floats: {
        'web-2': { id: 'web-2', kind: 'browser', title: 'W2', surface: 'float', surfaceFrame: { x: 10, y: 20, width: 400, height: 300 } },
      },
      floatOrder: ['web-2'],
      prefs: { compact: true },
    }
    const migrated = migrateLegacySplitState(legacy)
    expect(migrated).not.toBeNull()
    if (!migrated) return
    expect(migrated.model.floats).toHaveLength(1)
    expect(migrated.model.floats[0]).toMatchObject({ id: 'web-2', rect: { x: 10, y: 20, width: 400, height: 300 } })
    expect(areasOf(migrated.model).map(area => area.id)).toEqual(['main'])
    expect(migrated.dropped).toBe(0)
  })

  it('moves a v2 pane tab that claims float into the float collection', () => {
    const legacy = {
      version: 2,
      tree: { type: 'split', id: 's1', direction: 'columns', ratio: .5, first: { type: 'pane', id: 'main' }, second: { type: 'pane', id: 'aux' } },
      panes: {
        aux: {
          id: 'aux',
          tabs: [
            { id: 'web', kind: 'browser', title: '浏览器' },
            { id: 'web-float', kind: 'browser', title: 'F', surface: 'float', surfaceFrame: { x: 30, y: 40, width: 300, height: 220 } },
          ],
          activeTab: 'web',
        },
      },
    }
    const migrated = migrateLegacySplitState(legacy)
    expect(migrated).not.toBeNull()
    if (!migrated) return
    const aux = areasOf(migrated.model).find(area => area.id === 'aux')!
    expect(aux.tabs).toEqual(['web'])
    expect(migrated.model.floats.map(box => box.id)).toEqual(['web-float'])
  })

  it('drops only the broken surfaces/floats and counts them', () => {
    const legacy = {
      version: 2,
      tree: { type: 'split', id: 's1', direction: 'columns', ratio: .5, first: { type: 'pane', id: 'main' }, second: { type: 'pane', id: 'aux' } },
      panes: {
        aux: {
          id: 'aux',
          tabs: [
            { id: 'web', kind: 'browser', title: '浏览器' },
            { id: 'bad', kind: 'unknown-kind', title: '坏内容' },
          ],
          activeTab: 'web',
        },
      },
      floats: { broken: { id: 'broken', kind: 'browser', title: 'B', surfaceFrame: { x: 0, y: 0, width: Number.NaN, height: 10 } } },
    }
    const migrated = migrateLegacySplitState(legacy)
    expect(migrated).not.toBeNull()
    if (!migrated) return
    expect(migrated.dropped).toBeGreaterThanOrEqual(1)
    expect(migrated.model.surfaces.bad).toBeUndefined()
    // 坏矩形不挡迁移：浮层仍在，但换成默认落点。
    expect(migrated.model.floats.map(box => box.id)).toEqual(['broken'])
    expect(migrated.model.floats[0].rect.width).toBeGreaterThan(0)
  })

  it('drops unusable v4 entries instead of voiding the archive', () => {
    const raw = JSON.stringify({
      version: 4,
      surfaces: {
        agent: { id: 'agent', kind: 'agent', title: 'Agent' },
        ghost: { id: 'ghost', kind: 'nope', title: '坏' },
      },
      tree: {
        kind: 'split',
        direction: 'row',
        ratio: .5,
        a: { kind: 'leaf', area: { id: 'main', tabs: ['agent', 'ghost'], active: 'agent', role: 'main', axis: 'vertical' } },
        b: { kind: 'leaf', area: { id: 'aux', tabs: [], active: null, role: 'aux', axis: 'vertical' } },
      },
      floats: [
        { id: 'ghost', rect: { x: 0, y: 0, width: 10, height: 10 }, yieldEnabled: false },
        { id: 'agent', rect: { x: 0, y: 0, width: 10, height: 10 }, yieldEnabled: false },
      ],
      floatFocus: null,

      prefs: { compact: false },
    })
    const parsed = parseWorkspace(raw, fallback)
    expect(parsed.migrated).toBe(false)
    expect(parsed.dropped).toBeGreaterThanOrEqual(2)
    expect(parsed.model.surfaces.ghost).toBeUndefined()
    expect(parsed.model.floats).toEqual([])
    expect(areasOf(parsed.model)[0].tabs).toEqual(['agent'])
  })

  it('carries lastFloatRect through v4 and fills it during migration', () => {
    const model = { ...createWorkspace(refs, 'web'), lastFloatRect: { web: { x: 1, y: 2, width: 300, height: 200 } } }
    expect(parseWorkspace(serializeWorkspace(model), fallback).model.lastFloatRect).toEqual(model.lastFloatRect)

    const legacy = {
      version: 3,
      tree: { type: 'pane', id: 'main' },
      panes: {},
      floats: { w: { id: 'w', kind: 'browser', title: 'W', surface: 'float', surfaceFrame: { x: 10, y: 20, width: 300, height: 200 } } },
      floatOrder: ['w'],
    }
    const migrated = migrateLegacySplitState(legacy)
    expect(migrated).not.toBeNull()
    if (!migrated) return
    expect(migrated.model.lastFloatRect.w).toEqual({ x: 10, y: 20, width: 300, height: 200 })
  })

  it('treats a missing lastFloatRect as empty instead of dropping the archive', () => {
    const source = JSON.parse(serializeWorkspace(createWorkspace(refs, 'agent'))) as Record<string, unknown>
    delete source.lastFloatRect
    const parsed = parseWorkspace(JSON.stringify(source), fallback)
    expect(parsed.migrated).toBe(false)
    expect(parsed.model.lastFloatRect).toEqual({})
  })
})
