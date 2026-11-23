// user:“布局保存恢复；v1–v3 迁移，坏档按主档→备份→默认回退”+
// (只存模型不存 rect；迁移时把旧 split 存档的 tree/panes/mainTab/floats 收成 v4；
//  单个坏 surface/浮层只丢自己，整份认不出来才回 fallback)。

import {
  axisForKind,
  DEFAULT_FLOAT_RECT,
  normalizeWorkspace,
  readSurfaceDetails,
  WORKSPACE_VERSION,
  type AreaId,
  type FloatBox,
  type Rect,
  type SplitNode,
  type SurfaceId,
  type SurfaceKind,
  type SurfaceRef,
  type WorkspaceModel,
} from './model'

export const WORKSPACE_STORAGE_KEY = 'lamtools.workspace.v4'

const KIND_MAP: Record<string, SurfaceKind> = {
  agent: 'agent',
  conversation: 'conversation',
  browser: 'browser',
  file: 'file',
  page: 'file',
  editor: 'file',
  files: 'file',
  plugin: 'plugin',
  preview: 'preview',
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function readRect(value: unknown): Rect | null {
  const record = asRecord(value)
  if (!record) return null
  const keys = ['x', 'y', 'width', 'height'] as const
  if (!keys.every(key => typeof record[key] === 'number' && Number.isFinite(record[key]))) return null
  return {
    x: Math.round(record.x as number),
    y: Math.round(record.y as number),
    width: Math.max(1, Math.round(record.width as number)),
    height: Math.max(1, Math.round(record.height as number)),
  }
}

/** 旧存档与 v4 共用的内容描述读取：只认六类 kind，其余整条丢弃。 */
function readSurface(value: unknown): SurfaceRef | null {
  const record = asRecord(value)
  if (!record) return null
  const id = typeof record.id === 'string' ? record.id : null
  if (!id) return null
  const kind = typeof record.kind === 'string' ? KIND_MAP[record.kind] : undefined
  if (!kind) return null
  const title = typeof record.title === 'string' && record.title ? record.title : id
  const surface: SurfaceRef = { id, kind, title }
  if (typeof record.resource === 'string') surface.resource = record.resource
  if (typeof record.zoom === 'number' && Number.isFinite(record.zoom)) surface.zoom = record.zoom
  readSurfaceDetails(surface, record)
  if (kind === 'file' && !surface.fileView) {
    if (record.kind === 'editor' || record.kind === 'files' || record.kind === 'page') surface.fileView = record.kind
    else if (/^editor-\d+$/.test(id)) surface.fileView = 'editor'
    else if (/^files-\d+$/.test(id)) surface.fileView = 'files'
  }
  return surface
}

function leafById(node: SplitNode, areaId: AreaId): Extract<SplitNode, { kind: 'leaf' }>['area'] | null {
  if (node.kind === 'leaf') return node.area.id === areaId ? node.area : null
  return leafById(node.a, areaId) ?? leafById(node.b, areaId)
}

function firstLeaf(node: SplitNode): SplitNode & { kind: 'leaf' } {
  if (node.kind === 'leaf') return node
  return firstLeaf(node.a)
}

/**
 * user:“迁移 v1/v2（旧 split 存档）与 v3（floats 集合）→ v4”+
 * (旧 tree 的 columns/rows 映射成 row/column；panes 的标签集合变成 Area.tabs；
//  旧 mainTab 变成主区的活动标签；旧浮层（v3 的 floats 或 v1/v2 里 surface='float' 的标签）
//  搬进 FloatBox；认不出结构（没有 tree、递归全坏）才返回 null——交给上层回退)。
 */
export function migrateLegacySplitState(legacy: unknown): { model: WorkspaceModel; dropped: number } | null {
  const source = asRecord(legacy)
  if (!source) return null
  const version = typeof source.version === 'number' ? source.version : 0
  if (version < 1 || version > 3) return null

  let dropped = 0
  const surfaces: Record<SurfaceId, SurfaceRef> = {}
  const register = (raw: unknown): SurfaceId | null => {
    const ref = readSurface(raw)
    if (!ref) { dropped += 1; return null }
    if (!surfaces[ref.id]) surfaces[ref.id] = ref
    return ref.id
  }

  const panes = asRecord(source.panes) ?? {}
  const floatOrder = Array.isArray(source.floatOrder)
    ? source.floatOrder.filter((id): id is string => typeof id === 'string')
    : []
  const orderOf = (id: SurfaceId): number => {
    const index = floatOrder.indexOf(id)
    return index < 0 ? Number.MAX_SAFE_INTEGER : index
  }
  const floatEntries: Array<{ id: SurfaceId; rect: Rect; order: number }> = []
  const floatIds = new Set<SurfaceId>()
  const addFloat = (raw: unknown): void => {
    const ref = readSurface(raw)
    if (!ref) { dropped += 1; return }
    if (!surfaces[ref.id]) surfaces[ref.id] = ref
    if (floatIds.has(ref.id)) return
    const record = asRecord(raw)
    floatIds.add(ref.id)
    floatEntries.push({ id: ref.id, rect: (record ? readRect(record.surfaceFrame) : null) ?? { ...DEFAULT_FLOAT_RECT }, order: orderOf(ref.id) })
  }

  const floatMap = asRecord(source.floats)
  if (floatMap) {
    for (const [id, value] of Object.entries(floatMap)) {
      const record = asRecord(value)
      if (!record || record.id !== id) { dropped += 1; continue }
      addFloat(record)
    }
  }

  const mapNode = (raw: unknown): SplitNode | null => {
    const record = asRecord(raw)
    if (!record) return null
    if (record.type === 'pane') {
      const id = typeof record.id === 'string' ? record.id : null
      if (!id) { dropped += 1; return null }
      const pane = asRecord(panes[id])
      const rawTabs = Array.isArray(pane?.tabs) ? pane.tabs : []
      const activeRaw = typeof pane?.activeTab === 'string' ? pane.activeTab : null
      const tabs: SurfaceId[] = []
      let active: SurfaceId | null = null
      for (const rawTab of rawTabs) {
        const tab = asRecord(rawTab)
        if (tab?.surface === 'float') { addFloat(rawTab); continue }
        const surfaceId = register(rawTab)
        if (!surfaceId) continue
        tabs.push(surfaceId)
        if (activeRaw === surfaceId) active = surfaceId
      }
      if (!active) active = tabs[0] ?? null
      const surface = active ? surfaces[active] : undefined
      return {
        kind: 'leaf',
        area: {
          id,
          tabs,
          active,
          role: id === 'main' ? 'main' : 'aux',
          axis: surface ? axisForKind(surface.kind) : 'vertical',
        },
      }
    }
    if (record.type === 'split') {
      const a = mapNode(record.first)
      const b = mapNode(record.second)
      if (!a && !b) { dropped += 1; return null }
      if (!a) return b
      if (!b) return a
      const rawRatio = typeof record.ratio === 'number' && Number.isFinite(record.ratio) ? record.ratio : .5
      return {
        kind: 'split',
        direction: record.direction === 'rows' ? 'column' : 'row',
        ratio: Math.min(.98, Math.max(.02, rawRatio)),
        a,
        b,
      }
    }
    dropped += 1
    return null
  }

  const tree = mapNode(source.tree)
  if (!tree) return null

  // 旧 mainTab：主区当时显示的那份内容——迁移成主区的活动标签（其余标签留在其后）。
  let mainSurface: SurfaceId | null = null
  if (source.mainTab != null) mainSurface = register(source.mainTab)
  if (mainSurface) {
    const target = leafById(tree, 'main') ?? firstLeaf(tree).area
    if (!target.tabs.includes(mainSurface)) target.tabs.unshift(mainSurface)
    target.active = mainSurface
    const surface = surfaces[mainSurface]
    if (surface) target.axis = axisForKind(surface.kind)
  }

  const floats: FloatBox[] = [...floatEntries]
    .sort((a, b) => a.order - b.order)
    .map(entry => ({ id: entry.id, rect: entry.rect, yieldEnabled: false }))

  // 旧档没有“上一次浮层尺寸”字段：用这一份里现有的浮层矩形补上（缺失就是空对象，不影响迁移）。
  const lastFloatRect: Record<SurfaceId, Rect> = {}
  for (const box of floats) lastFloatRect[box.id] = { ...box.rect }

  const model: WorkspaceModel = {
    version: WORKSPACE_VERSION,
    surfaces,
    tree,
    floats,
    floatFocus: null,

    lastFloatRect,
    prefs: { compact: asRecord(source.prefs)?.compact === true || source.compact === true },
  }
  return { model: normalizeWorkspace(model), dropped }
}

function readV4(source: Record<string, unknown>): { model: WorkspaceModel; dropped: number } | null {
  let dropped = 0
  const surfaces: Record<SurfaceId, SurfaceRef> = {}
  const rawSurfaces = asRecord(source.surfaces) ?? {}
  for (const [id, value] of Object.entries(rawSurfaces)) {
    const ref = readSurface(value)
    if (!ref || ref.id !== id) { dropped += 1; continue }
    surfaces[id] = ref
  }

  const mapTree = (raw: unknown): SplitNode | null => {
    const record = asRecord(raw)
    if (!record) return null
    if (record.kind === 'leaf') {
      const area = asRecord(record.area)
      const id = typeof area?.id === 'string' ? area.id : null
      if (!area || !id) { dropped += 1; return null }
      const rawTabs = Array.isArray(area.tabs) ? area.tabs : []
      const tabs: SurfaceId[] = []
      for (const tab of rawTabs) {
        if (typeof tab !== 'string' || !surfaces[tab]) { dropped += 1; continue }
        if (!tabs.includes(tab)) tabs.push(tab)
      }
      const active = typeof area.active === 'string' && tabs.includes(area.active) ? area.active : tabs[0] ?? null
      const surface = active ? surfaces[active] : undefined
      return {
        kind: 'leaf',
        area: {
          id,
          tabs,
          active,
          role: area.role === 'main' ? 'main' : 'aux',
          axis: surface ? axisForKind(surface.kind) : area.axis === 'horizontal' ? 'horizontal' : 'vertical',
        },
      }
    }
    if (record.kind === 'split') {
      const a = mapTree(record.a)
      const b = mapTree(record.b)
      if (!a && !b) { dropped += 1; return null }
      if (!a) return b
      if (!b) return a
      const ratio = typeof record.ratio === 'number' && Number.isFinite(record.ratio) ? record.ratio : .5
      return {
        kind: 'split',
        direction: record.direction === 'column' ? 'column' : 'row',
        ratio: Math.min(.98, Math.max(.02, ratio)),
        a,
        b,
      }
    }
    dropped += 1
    return null
  }

  const tree = mapTree(source.tree)
  if (!tree) return null

  const floats: FloatBox[] = []
  const floatIds = new Set<SurfaceId>()
  const rawFloats = Array.isArray(source.floats) ? source.floats : []
  for (const value of rawFloats) {
    const record = asRecord(value)
    const id = typeof record?.id === 'string' ? record.id : null
    if (!record || !id || !surfaces[id] || floatIds.has(id)) { dropped += 1; continue }
    const rect = readRect(record.rect)
    if (!rect) { dropped += 1; continue }
    floatIds.add(id)
    floats.push({ id, rect, yieldEnabled: record.yieldEnabled === true })
  }


  // user:“解除固定优先恢复上一次浮层尺寸”+(记录只是缓存：缺失或坏值不算丢档，也不计入 dropped)。
  const lastFloatRect: Record<SurfaceId, Rect> = {}
  for (const [id, value] of Object.entries(asRecord(source.lastFloatRect) ?? {})) {
    if (!surfaces[id]) continue
    const rect = readRect(value)
    if (!rect) continue
    lastFloatRect[id] = rect
  }

  const prefs = asRecord(source.prefs)
  const layout = prefs?.layout
  const model: WorkspaceModel = {
    version: WORKSPACE_VERSION,
    surfaces,
    tree,
    floats,
    floatFocus: typeof source.floatFocus === 'string' && floatIds.has(source.floatFocus) ? source.floatFocus : null,
    // user:“聚焦是一个无意义功能，移除”+(旧布局的聚焦标记不参与恢复，所有分屏正常显示)。

    lastFloatRect,
    prefs: {
      compact: prefs?.compact === true,
      ...(layout === 'agent' || layout === 'browser' ? { layout } : {}),
    },
  }
  // 结构层再收拾一次：去重、收拢因去重空掉的区域、保证恰好一个 main。
  return { model: normalizeWorkspace(model), dropped }
}

export function serializeWorkspace(model: WorkspaceModel): string {
  return JSON.stringify(model)
}

/**
 * 读档：认 v4 就直接校验；认 v1/v2/v3 就迁移；其余（未知版本、JSON 坏、结构认不出）回 fallback。
 * dropped 是“这一份里被丢掉的单个坏条目数”，供上层打一条诊断，不影响回退语义。
 */
export function parseWorkspace(raw: string | null, fallback: WorkspaceModel): { model: WorkspaceModel; migrated: boolean; dropped: number } {
  if (!raw) return { model: fallback, migrated: false, dropped: 0 }
  let parsed: unknown
  try { parsed = JSON.parse(raw) } catch { return { model: fallback, migrated: false, dropped: 0 } }
  const source = asRecord(parsed)
  if (!source) return { model: fallback, migrated: false, dropped: 0 }
  const version = typeof source.version === 'number' ? source.version : null
  if (version === WORKSPACE_VERSION) {
    const result = readV4(source)
    return result ? { model: result.model, migrated: false, dropped: result.dropped } : { model: fallback, migrated: false, dropped: 0 }
  }
  if (version === 1 || version === 2 || version === 3) {
    const result = migrateLegacySplitState(source)
    return result ? { model: result.model, migrated: true, dropped: result.dropped } : { model: fallback, migrated: false, dropped: 0 }
  }
  return { model: fallback, migrated: false, dropped: 0 }
}
