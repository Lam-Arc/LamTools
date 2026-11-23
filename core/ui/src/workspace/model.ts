// user:“分屏系统重做…布局只描述区域，不描述内容；一个 Surface 同一时刻只有一个 Placement”+
// (V2 引擎最底层：只有纯数据与纯函数。内容实例放 surfaces 注册表，位置只有三种——区域 / 浮层 / 聚焦，
//  布局树只描述“区域怎么切”，绝不承载内容状态；任何变更后由 normalizeWorkspace 收拾不变量)。

export type SurfaceId = string
export type AreaId = string

export interface Rect { x: number; y: number; width: number; height: number }

export type SurfaceKind = 'agent' | 'conversation' | 'browser' | 'file' | 'plugin' | 'preview'

export interface SurfaceRef {
  id: SurfaceId
  kind: SurfaceKind
  title: string
  resource?: string
  zoom?: number
  /** user:“快速精准高效的解决”+(存档保留标签类型和所属范围，布局仍只计算位置)。 */
  fileView?: 'page' | 'editor' | 'files'
  root?: string
  projectId?: string
  sessionId?: string
  profile?: string
}

export type AreaAxis = 'vertical' | 'horizontal'
export type AreaRole = 'main' | 'aux'

export interface Area {
  id: AreaId
  tabs: SurfaceId[]
  active: SurfaceId | null
  role: AreaRole
  axis: AreaAxis
}

export type SplitNode =
  | { kind: 'leaf'; area: Area }
  | { kind: 'split'; direction: 'row' | 'column'; ratio: number; a: SplitNode; b: SplitNode }

// user:“浮层独立矩形 + z 序；每层独立的「自由让位」开关（默认关）”+(z 序 = 数组顺序，末尾最上)。
export interface FloatBox { id: SurfaceId; rect: Rect; yieldEnabled: boolean }

export interface WorkspaceModel {
  version: 4
  surfaces: Record<SurfaceId, SurfaceRef>
  tree: SplitNode
  floats: FloatBox[]
  floatFocus: SurfaceId | null
  // user:“解除固定时优先恢复该内容上一次合理的浮层尺寸；位置与当前区域保持视觉联系”+
  // (只记最近一次“真的浮动过”的矩形：pin 之后记录保留，unpin 优先按它恢复；纯 z 序/焦点操作不覆写)。
  lastFloatRect: Record<SurfaceId, Rect>
  prefs: { compact: boolean; layout?: WorkspaceLayout }
}

export type WorkspaceLayout = 'agent' | 'browser'

export const WORKSPACE_VERSION = 4 as const

/** user:“目前库和file处于分屏时没有关闭键”+(各类内容共用顶部标签，Agent 主区沿用左侧栏)。 */
export function axisForKind(kind: SurfaceKind): AreaAxis {
  return kind === 'agent' ? 'vertical' : 'horizontal'
}

/** 迁移/新建浮层时的确定落点（compute 会再按视口收紧一次）。 */
export const DEFAULT_FLOAT_RECT: Rect = { x: 160, y: 120, width: 480, height: 340 }

/** 布局是不可变数据：每次变更都从克隆开始，避免调用方与引擎共享引用。 */
export function cloneModel(model: WorkspaceModel): WorkspaceModel {
  return JSON.parse(JSON.stringify(model)) as WorkspaceModel
}

/**
 * user:“主工作区始终存在，是视觉中心”+
 * (新建工作区就是“一块主区 + 一份内容”；没有浮层、没有折叠、没有聚焦，
 *  预设置全部取默认值，保证第一次 compute 的结果是确定且铺满的)。
 */
export function createWorkspace(surfaces: SurfaceRef[], seed: SurfaceId): WorkspaceModel {
  const registry: Record<SurfaceId, SurfaceRef> = {}
  for (const surface of surfaces) registry[surface.id] = { ...surface }
  const seedRef = registry[seed]
  const area: Area = {
    id: 'main',
    tabs: seedRef ? [seed] : [],
    active: seedRef ? seed : null,
    role: 'main',
    axis: seedRef ? axisForKind(seedRef.kind) : 'vertical',
  }
  return {
    version: WORKSPACE_VERSION,
    surfaces: registry,
    tree: { kind: 'leaf', area },
    floats: [],
    floatFocus: null,
    lastFloatRect: {},
    prefs: { compact: false },
  }
}

/** 区域按树的深度优先顺序给出（a 在左/上，b 在右/下）：这是唯一稳定的顺序口径。 */
export function areasOf(model: WorkspaceModel): Area[] {
  const list: Area[] = []
  const walk = (node: SplitNode): void => {
    if (node.kind === 'leaf') { list.push(node.area); return }
    walk(node.a)
    walk(node.b)
  }
  walk(model.tree)
  return list
}

/** 内容当前落在哪儿：区域优先、浮层次之；两处都有时以区域为准（normalize 会消掉重复）。 */
export function placeOf(model: WorkspaceModel, id: SurfaceId): { kind: 'area'; areaId: AreaId } | { kind: 'float' } | null {
  for (const area of areasOf(model)) if (area.tabs.includes(id)) return { kind: 'area', areaId: area.id }
  if (model.floats.some(box => box.id === id)) return { kind: 'float' }
  return null
}

/** 当前有落点的内容 id（区域顺序 + 浮层 z 序），供渲染层按同一口径遍历。 */
export function surfaceIdsOf(model: WorkspaceModel): SurfaceId[] {
  const ids: SurfaceId[] = []
  const seen = new Set<SurfaceId>()
  for (const area of areasOf(model)) {
    for (const id of area.tabs) if (!seen.has(id)) { seen.add(id); ids.push(id) }
  }
  for (const box of model.floats) if (!seen.has(box.id)) { seen.add(box.id); ids.push(box.id) }
  return ids
}

function finite(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function sanitizeRect(value: unknown, fallback: Rect): Rect {
  const source = (value ?? {}) as Partial<Rect>
  return {
    x: finite(source.x, fallback.x),
    y: finite(source.y, fallback.y),
    width: Math.max(1, finite(source.width, fallback.width)),
    height: Math.max(1, finite(source.height, fallback.height)),
  }
}

export function readSurfaceDetails(surface: SurfaceRef, source: Partial<Record<keyof SurfaceRef, unknown>>): void {
  if (source.fileView === 'page' || source.fileView === 'editor' || source.fileView === 'files') surface.fileView = source.fileView
  for (const key of ['root', 'projectId', 'sessionId', 'profile'] as const) {
    const value = source[key]
    if (typeof value === 'string' && value) surface[key] = value
  }
}

function sanitizeSurface(value: unknown): SurfaceRef | null {
  const source = (value ?? {}) as Partial<SurfaceRef>
  const kinds: SurfaceKind[] = ['agent', 'conversation', 'browser', 'file', 'plugin', 'preview']
  if (typeof source.id !== 'string' || !source.id) return null
  if (typeof source.kind !== 'string' || !kinds.includes(source.kind as SurfaceKind)) return null
  if (typeof source.title !== 'string') return null
  const surface: SurfaceRef = { id: source.id, kind: source.kind as SurfaceKind, title: source.title }
  if (typeof source.resource === 'string') surface.resource = source.resource
  if (typeof source.zoom === 'number' && Number.isFinite(source.zoom)) surface.zoom = source.zoom
  readSurfaceDetails(surface, source)
  return surface
}

/**
 * user:“一个 Surface 同一时刻只有一个 Placement；任何变更后跑一次 normalize（去重、收拢空区）”+
 * (这里只做结构收拾，不夹浮层几何——几何由 compute 按视口收紧，模型保留用户摆过的原值。
//  空区口径：因“内容被去重/失效”而空掉的区域收拢；本来就空着的区域保留（新建分屏要能留一块空位）。
//  另外保证恰好一个 main 区域、active 一定在 tabs 里、axis 跟着主内容类型走)。
 */
export function normalizeWorkspace(model: WorkspaceModel): WorkspaceModel {
  const surfaces: Record<SurfaceId, SurfaceRef> = {}
  for (const [id, value] of Object.entries(model.surfaces ?? {})) {
    const surface = sanitizeSurface(value)
    if (surface && surface.id === id) surfaces[id] = surface
  }

  const seen = new Set<SurfaceId>()
  const prune = (node: SplitNode): SplitNode | null => {
    if (node.kind === 'leaf') {
      const original = Array.isArray(node.area.tabs) ? node.area.tabs : []
      const tabs: SurfaceId[] = []
      for (const id of original) {
        if (typeof id !== 'string' || !surfaces[id] || seen.has(id)) continue
        seen.add(id)
        tabs.push(id)
      }
      // 内容全部被去重/失效而空掉：这块区域已经没有存在意义，收拢。
      if (original.length > 0 && tabs.length === 0) return null
      const active = typeof node.area.active === 'string' && tabs.includes(node.area.active)
        ? node.area.active
        : tabs[0] ?? null
      const axis = active && surfaces[active] ? axisForKind(surfaces[active].kind) : node.area.axis ?? 'vertical'
      return { kind: 'leaf', area: { id: node.area.id, tabs, active, role: node.area.role === 'main' ? 'main' : 'aux', axis } }
    }
    const a = prune(node.a)
    const b = prune(node.b)
    if (!a && !b) return null
    if (!a) return b
    if (!b) return a
    const ratio = finite(node.ratio, .5)
    return { kind: 'split', direction: node.direction === 'column' ? 'column' : 'row', ratio: Math.min(.98, Math.max(.02, ratio)), a, b }
  }

  let tree = prune(model.tree)
  if (!tree) {
    tree = { kind: 'leaf', area: { id: 'main', tabs: [], active: null, role: 'main', axis: 'vertical' } }
  }

  // 恰好一个 main：多余降为 aux，没有就提升第一个。
  const areas = areasOf({ ...model, tree })
  let promoted = false
  for (const area of areas) {
    if (area.role === 'main' && !promoted) { promoted = true; continue }
    area.role = 'aux'
  }
  if (!promoted && areas.length) areas[0].role = 'main'

  const floats: FloatBox[] = []
  const floatSeen = new Set<SurfaceId>()
  for (const box of Array.isArray(model.floats) ? model.floats : []) {
    if (!box || typeof box.id !== 'string') continue
    if (!surfaces[box.id] || seen.has(box.id) || floatSeen.has(box.id)) continue
    floatSeen.add(box.id)
    floats.push({ id: box.id, rect: sanitizeRect(box.rect, DEFAULT_FLOAT_RECT), yieldEnabled: box.yieldEnabled === true })
  }

  // user:“解除固定优先恢复该内容上一次合理的浮层尺寸”+(记录按注册表保留，与“当前是否浮动”无关；
  //  正在浮动的矩形就是最新一次，顺手同步，避免历史/手工构造的模型里出现两份不一致)。
  const lastFloatRect: Record<SurfaceId, Rect> = {}
  for (const [id, value] of Object.entries(model.lastFloatRect ?? {})) {
    if (!surfaces[id]) continue
    const source = (value ?? {}) as Partial<Rect>
    const usable = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)
    if (!usable(source.x) || !usable(source.y) || !usable(source.width) || !usable(source.height)) continue
    lastFloatRect[id] = {
      x: Math.round(source.x),
      y: Math.round(source.y),
      width: Math.max(1, Math.round(source.width)),
      height: Math.max(1, Math.round(source.height)),
    }
  }
  for (const box of floats) lastFloatRect[box.id] = { ...box.rect }


  return {
    version: WORKSPACE_VERSION,
    surfaces,
    tree,
    floats,
    floatFocus: model.floatFocus && floatSeen.has(model.floatFocus) ? model.floatFocus : null,
    lastFloatRect,
    prefs: {
      compact: model.prefs?.compact === true,
      ...(model.prefs?.layout === 'agent' || model.prefs?.layout === 'browser' ? { layout: model.prefs.layout } : {}),
    },
  }
}
