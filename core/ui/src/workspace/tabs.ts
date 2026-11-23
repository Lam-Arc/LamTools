// user:“内容标签区…同一 Area 排序、跨 Area 移动”+(标签集合只回答“谁在哪块区域、谁是活动标签”；
// 空区收拢在这里显式处理，不依赖几何，也不销毁内容注册表里的 SurfaceRef)。

import {
  areasOf,
  cloneModel,
  normalizeWorkspace,
  type AreaId,
  type SplitNode,
  type SurfaceId,
  type SurfaceRef,
  type WorkspaceModel,
} from './model'

function removeLeaf(node: SplitNode, areaId: AreaId): SplitNode | null {
  if (node.kind === 'leaf') return node.area.id === areaId ? null : node
  const a = removeLeaf(node.a, areaId)
  const b = removeLeaf(node.b, areaId)
  if (!a) return b
  if (!b) return a
  return { ...node, a, b }
}

function clampIndex(index: number, length: number): number {
  if (!Number.isFinite(index)) return length
  return Math.min(length, Math.max(0, Math.round(index)))
}

/** 把内容登记进注册表（同 id 以最新描述为准；内容实例本身不在这里重建）。 */
function register(model: WorkspaceModel, surface: SurfaceRef): void {
  if (!surface || typeof surface.id !== 'string' || !surface.id) return
  model.surfaces[surface.id] = { ...surface }
}

function detach(model: WorkspaceModel, surfaceId: SurfaceId): void {
  for (const area of areasOf(model)) {
    const index = area.tabs.indexOf(surfaceId)
    if (index < 0) continue
    area.tabs.splice(index, 1)
    if (area.active === surfaceId) area.active = area.tabs[Math.min(index, area.tabs.length - 1)] ?? null
  }
  model.floats = model.floats.filter(box => box.id !== surfaceId)
  if (model.floatFocus === surfaceId) model.floatFocus = null
}

/** user:“拖到标签栏 = 挪进去”+(加标签先摘掉别处的同一份，保证一个 Surface 只有一处落点)。 */
export function addTab(model: WorkspaceModel, areaId: AreaId, surface: SurfaceRef, index?: number): WorkspaceModel {
  const clone = cloneModel(model)
  register(clone, surface)
  if (!areasOf(clone).some(area => area.id === areaId)) return model
  detach(clone, surface.id)
  const area = areasOf(clone).find(item => item.id === areaId)!
  const at = clampIndex(index ?? area.tabs.length, area.tabs.length)
  area.tabs.splice(at, 0, surface.id)
  if (!area.active) area.active = surface.id
  return normalizeWorkspace(clone)
}

/** user:“关标签 = 空区自动收拢”+(最后一块区域保留空位——工作区永远有主区)。 */
export function closeTab(model: WorkspaceModel, areaId: AreaId, surfaceId: SurfaceId): WorkspaceModel {
  const clone = cloneModel(model)
  const area = areasOf(clone).find(item => item.id === areaId)
  if (!area) return model
  const index = area.tabs.indexOf(surfaceId)
  if (index < 0) return model
  area.tabs.splice(index, 1)
  if (area.active === surfaceId) area.active = area.tabs[Math.min(index, area.tabs.length - 1)] ?? null
  if (area.role !== 'main' && area.tabs.length === 0 && areasOf(clone).length > 1) {
    const tree = removeLeaf(clone.tree, areaId)
    if (tree) clone.tree = tree
  }
  return normalizeWorkspace(clone)
}

/** user:“跨 Area 移动标签”+(源区空了就收拢；移动本身不复制内容，只换位置)。 */
export function moveTab(
  model: WorkspaceModel,
  from: { areaId: AreaId; index: number },
  to: { areaId: AreaId; index: number },
): WorkspaceModel {
  if (from.areaId === to.areaId) return reorderTab(model, from.areaId, from.index, to.index)
  const clone = cloneModel(model)
  const source = areasOf(clone).find(item => item.id === from.areaId)
  const target = areasOf(clone).find(item => item.id === to.areaId)
  if (!source || !target) return model
  const surfaceId = source.tabs[from.index]
  if (!surfaceId) return model
  source.tabs.splice(from.index, 1)
  if (source.active === surfaceId) source.active = source.tabs[Math.min(from.index, source.tabs.length - 1)] ?? null
  if (source.tabs.length === 0 && areasOf(clone).length > 1) {
    const tree = removeLeaf(clone.tree, from.areaId)
    if (tree) clone.tree = tree
  }
  const area = areasOf(clone).find(item => item.id === to.areaId)!
  const at = clampIndex(to.index, area.tabs.length)
  area.tabs.splice(at, 0, surfaceId)
  area.active = surfaceId
  return normalizeWorkspace(clone)
}

export function selectTab(model: WorkspaceModel, areaId: AreaId, surfaceId: SurfaceId): WorkspaceModel {
  const area = areasOf(model).find(item => item.id === areaId)
  if (!area || !area.tabs.includes(surfaceId) || area.active === surfaceId) return model
  const clone = cloneModel(model)
  const target = areasOf(clone).find(item => item.id === areaId)!
  target.active = surfaceId
  return clone
}

export function reorderTab(model: WorkspaceModel, areaId: AreaId, from: number, to: number): WorkspaceModel {
  const area = areasOf(model).find(item => item.id === areaId)
  if (!area) return model
  // 越界的 from 不是“移动最后一条”，而是没有这次操作：原样返回，避免把用户没点的标签挪走。
  if (!Number.isInteger(from) || from < 0 || from >= area.tabs.length) return model
  const clone = cloneModel(model)
  const target = areasOf(clone).find(item => item.id === areaId)!
  const [surfaceId] = target.tabs.splice(from, 1)
  target.tabs.splice(clampIndex(to, target.tabs.length), 0, surfaceId)
  return clone
}
