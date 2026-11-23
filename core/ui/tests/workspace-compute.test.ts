import { describe, expect, it } from 'vitest'
import {
  compactLimits,
  computeWorkspace,
  DEFAULT_CHROME,
  DEFAULT_LIMITS,
  type Issue,
} from '../src/workspace/compute'
import { areasOf, createWorkspace, normalizeWorkspace, type Area, type Rect, type SplitNode, type SurfaceRef, type WorkspaceModel } from '../src/workspace/model'
import { splitArea } from '../src/workspace/ops'

// user:“任意树 × 任意视口 → 铺满 / 无重叠 / 每区 ≥ 下限 或 insufficient”+
// (属性测试用固定种子的确定性 PRNG：引擎无随机，测试也不引入 Date/random)。

const refs: SurfaceRef[] = [
  { id: 'agent', kind: 'agent', title: 'Agent' },
  { id: 'web', kind: 'browser', title: '浏览器' },
]

function mulberry32(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6D2B79F5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const EDGES = ['left', 'right', 'top', 'bottom'] as const

function randomModel(seed: number): WorkspaceModel {
  const rand = mulberry32(seed)
  let model = createWorkspace(refs, 'agent')
  const target = 1 + Math.floor(rand() * 6)
  for (let index = 0; index < target; index += 1) {
    const areas = areasOf(model)
    const area = areas[Math.floor(rand() * areas.length)]
    const edge = EDGES[Math.floor(rand() * EDGES.length)]
    const result = splitArea(model, area.id, edge)
    if (result.ok) model = result.model
  }
  return model
}

const viewports: Rect[] = [
  { x: 0, y: 0, width: 1440, height: 900 },
  { x: 0, y: 0, width: 1152, height: 720 }, // dpr 1.25
  { x: 0, y: 0, width: 960, height: 640 },  // dpr 1.5
  { x: 0, y: 0, width: 778, height: 500 },  // dpr 1.85
  { x: 0, y: 0, width: 731, height: 500 },  // 刚放不下
  { x: 0, y: 0, width: 40, height: 30 },
  { x: 0, y: 0, width: 1, height: 1 },
  { x: 0, y: 0, width: 0, height: 0 },
  { x: 0, y: 0, width: -100, height: -50 },
  { x: 0, y: 0, width: 3840, height: 2160 },
]

function overlaps(a: Rect, b: Rect): boolean {
  return Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > 0
    && Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > 0
}

function leaf(id: string, tabs: string[], role: 'main' | 'aux'): SplitNode {
  const area: Area = { id, tabs, active: tabs[0] ?? null, role, axis: 'vertical' }
  return { kind: 'leaf', area }
}

describe('computeWorkspace invariants', () => {
  it('fills, never overlaps and never goes negative across 50 random trees × 10 viewports', () => {
    for (let seed = 1; seed <= 50; seed += 1) {
      const model = randomModel(seed)
      for (const viewport of viewports) {
        const geometry = computeWorkspace(model, viewport, { gap: 0 })
        const entries = Object.values(geometry.areas)
        const insufficient = geometry.issues.some((issue: Issue) => issue.code === 'insufficient')

        for (const value of entries) {
          expect(Number.isInteger(value.rect.x)).toBe(true)
          expect(Number.isInteger(value.rect.y)).toBe(true)
          expect(value.rect.width).toBeGreaterThanOrEqual(0)
          expect(value.rect.height).toBeGreaterThanOrEqual(0)
        }
        for (let i = 0; i < entries.length; i += 1) {
          for (let j = i + 1; j < entries.length; j += 1) {
            expect(overlaps(entries[i].rect, entries[j].rect)).toBe(false)
          }
        }
        if (!insufficient) {
          const width = Math.max(0, viewport.width)
          const height = Math.max(0, viewport.height)
          const areaById = new Map(areasOf(model).map(area => [area.id, area]))
          for (const [id, value] of Object.entries(geometry.areas)) {
            const area = areaById.get(id)
            const limit = area?.role === 'main' ? DEFAULT_LIMITS.main : DEFAULT_LIMITS.aux
            expect(value.rect.width).toBeGreaterThanOrEqual(limit.width)
            expect(value.rect.height).toBeGreaterThanOrEqual(limit.height)
          }
          const sum = entries.reduce((total, value) => total + value.rect.width * value.rect.height, 0)
          expect(sum).toBe(width * height)
        }
      }
    }
  })

  it('keeps two areas as a full left/right or top/bottom split (no corner panel)', () => {
    const workspace = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      tree: { kind: 'split', direction: 'row', ratio: .37, a: leaf('main', ['agent'], 'main'), b: leaf('aux', ['web'], 'aux') },
    })
    const geometry = computeWorkspace(workspace, { x: 0, y: 0, width: 1200, height: 800 }, { gap: 0 })
    const main = geometry.areas.main.rect
    const aux = geometry.areas.aux.rect
    expect(main.y).toBe(aux.y)
    expect(main.height).toBe(aux.height)
    expect(main.width + aux.width).toBe(1200)
  })

  it('degrades to compact limits when prefs.compact is set, and reports insufficient otherwise', () => {
    // 731 宽：默认下限放不下（420+2+320=742），紧凑下限放得下（361+2+275=638）。
    const workspace = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      tree: { kind: 'split', direction: 'row', ratio: .5, a: leaf('main', ['agent'], 'main'), b: leaf('aux', ['web'], 'aux') },
    })
    const normal = computeWorkspace(workspace, { x: 0, y: 0, width: 731, height: 500 })
    expect(normal.issues.some(issue => issue.code === 'insufficient')).toBe(true)

    const compact: WorkspaceModel = { ...workspace, prefs: { compact: true } }
    const geometry = computeWorkspace(compact, { x: 0, y: 0, width: 731, height: 500 })
    expect(geometry.issues.some(issue => issue.code === 'insufficient')).toBe(false)
    const limits = compactLimits(DEFAULT_LIMITS)
    expect(geometry.areas.main.rect.width).toBeGreaterThanOrEqual(limits.main.width)
    expect(geometry.areas.aux.rect.width).toBeGreaterThanOrEqual(limits.aux.width)
  })


  it('subtracts header (and tabbar only on horizontal axes) from contentRect', () => {
    const workspace = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      tree: { kind: 'split', direction: 'row', ratio: .5, a: leaf('main', ['agent'], 'main'), b: leaf('aux', ['web'], 'aux') },
    })
    const geometry = computeWorkspace(workspace, { x: 0, y: 0, width: 1200, height: 800 }, { gap: 0 })
    const header = DEFAULT_CHROME.header
    const tabbar = DEFAULT_CHROME.tabbar
    // 纵向（Agent）：标签条在侧栏，不占内容区高度。
    expect(geometry.areas.main.chrome.tabbar).toBe('hidden')
    expect(geometry.areas.main.contentRect).toEqual({ x: 0, y: header, width: geometry.areas.main.rect.width, height: 800 - header })
    // 横向（Browser）：页眉 + 标签条都在顶部。
    expect(geometry.areas.aux.chrome.tabbar).toBe('full')
    expect(geometry.areas.aux.contentRect.y).toBe(header + tabbar)
    expect(geometry.areas.aux.contentRect.height).toBe(800 - header - tabbar)
    expect(geometry.areas.aux.chrome.header).toBe(header)
  })

  it('clamps floats into the viewport with at least 1px, keeping sizes when they fit', () => {
    const workspace: WorkspaceModel = normalizeWorkspace({
      ...createWorkspace(refs, 'agent'),
      floats: [{ id: 'web', rect: { x: 2000, y: -40, width: 480, height: 300 }, yieldEnabled: false }],
    })
    const geometry = computeWorkspace(workspace, { x: 0, y: 0, width: 1200, height: 800 })
    expect(geometry.floats.web).toEqual({ x: 720, y: 0, width: 480, height: 300 })

    const tiny = computeWorkspace(workspace, { x: 0, y: 0, width: 0, height: 0 })
    expect(tiny.floats.web.width).toBeGreaterThanOrEqual(1)
    expect(tiny.floats.web.height).toBeGreaterThanOrEqual(1)
  })
})
