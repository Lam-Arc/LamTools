/**
 * Ping 工作台菜单树（纯函数）。
 *
 * user:“菜单树支持拖动排序、创建父项、拖放成子项、复制、隐藏、禁用、删除；
 * 最多三级”+
 * (当前配置用 group/subring 表达父子关系；这里只做稳定的排序、子树收集和
 *  深度限制，生产环与编辑器读的是同一份 sectors。)
 */
import type { PingSectorConfig } from '../config.ts'

export interface PingTreeNode {
  sector: PingSectorConfig
  depth: number
  children: PingTreeNode[]
}

export const PING_MAX_DEPTH = 3

export function childGroupOf(parent: PingSectorConfig): string {
  return parent.subring || parent.id
}

/** 构建菜单树；未启用项也保留在编辑器里，方便重新启用。 */
export function buildPingTree(sectors: PingSectorConfig[]): PingTreeNode[] {
  const visit = (group: string | null, depth: number): PingTreeNode[] => sectors
    .filter(sector => (group === null ? !sector.group : sector.group === group))
    .filter((sector, index, list) => list.findIndex(item => item.id === sector.id) === index)
    .map(sector => ({
      sector,
      depth,
      children: depth < PING_MAX_DEPTH ? visit(childGroupOf(sector), depth + 1) : [],
    }))
  return visit(null, 1)
}

export function flattenTree(nodes: PingTreeNode[]): PingTreeNode[] {
  return nodes.flatMap(node => [node, ...flattenTree(node.children)])
}

/** 删除父项时连同其所有子项一起删，避免留下无父的孤儿。 */
export function collectSubtreeIds(sectors: PingSectorConfig[], id: string): Set<string> {
  const ids = new Set<string>([id])
  const queue = sectors.filter(sector => sector.id === id)
  while (queue.length > 0) {
    const parent = queue.shift()!
    const group = childGroupOf(parent)
    for (const sector of sectors) {
      if (ids.has(sector.id)) continue
      if (sector.group === group) {
        ids.add(sector.id)
        queue.push(sector)
      }
    }
  }
  return ids
}

/**
 * 在同一父级内上移/下移。数组顺序就是生产环的显示顺序。
 * 返回新数组；越界时原样返回。
 */
export function movePingSector(
  sectors: PingSectorConfig[],
  id: string,
  delta: -1 | 1,
): PingSectorConfig[] {
  const index = sectors.findIndex(sector => sector.id === id)
  if (index < 0) return sectors
  const group = sectors[index].group || ''
  const siblings = sectors
    .map((sector, at) => ({ sector, at }))
    .filter(item => (item.sector.group || '') === group)
  const position = siblings.findIndex(item => item.sector.id === id)
  const target = position + delta
  if (position < 0 || target < 0 || target >= siblings.length) return sectors
  const next = [...sectors]
  const a = sectors.indexOf(siblings[position].sector)
  const b = sectors.indexOf(siblings[target].sector)
  ;[next[a], next[b]] = [next[b], next[a]]
  return next
}

export function pingActionLabel(sector: PingSectorConfig): string {
  if (sector.kind === 'select') return '打开截图框选'
  if (sector.kind === 'chat') return '打开主界面会话'
  if (sector.kind === 'switch') return '切换 Ping 目标会话'
  if (sector.kind === 'question') return '截图 + 标记「?」并发送'
  if (sector.kind === 'exclamation') return '截图 + 标记「!」并发送'
  if (sector.kind === 'note') return '截图 + 标记并记录'
  if (sector.kind === 'subring') return `展开子菜单（${sector.subring || sector.id}）`
  if (sector.kind === 'custom') return sector.action ? `本地动作：${sector.action}` : '未绑定本地动作'
  return '未配置'
}


function parentMap(sectors: PingSectorConfig[]): Map<string, PingSectorConfig> {
  const map = new Map<string, PingSectorConfig>()
  for (const parent of sectors) {
    map.set(childGroupOf(parent), parent)
  }
  return map
}

/** 节点深度（一级 = 1）；找不到返回 0。 */
export function pingNodeDepth(sectors: PingSectorConfig[], id: string): number {
  const byId = new Map(sectors.map(sector => [sector.id, sector]))
  const parents = parentMap(sectors)
  let depth = 0
  let current = byId.get(id)
  while (current && depth < 10) {
    depth += 1
    if (!current.group) break
    current = parents.get(current.group)
  }
  return current ? depth : 0
}

/** 以该节点为根的子树高度（叶子 = 1）。 */
export function pingSubtreeHeight(sectors: PingSectorConfig[], id: string): number {
  const target = sectors.find(sector => sector.id === id)
  if (!target) return 0
  const group = childGroupOf(target)
  const children = sectors.filter(sector => sector.group === group)
  if (children.length === 0) return 1
  return 1 + Math.max(...children.map(child => pingSubtreeHeight(sectors, child.id)))
}

/**
 * 同层拖动排序：把 dragId 放到 targetId 前/后。
 * 不同父级不在这里处理，必须显式使用 reparentPingSector。
 */
export function movePingSectorBeside(
  sectors: PingSectorConfig[],
  dragId: string,
  targetId: string,
  position: 'before' | 'after',
): PingSectorConfig[] {
  if (dragId === targetId) return sectors
  const drag = sectors.find(sector => sector.id === dragId)
  const target = sectors.find(sector => sector.id === targetId)
  if (!drag || !target) return sectors
  if ((drag.group || '') !== (target.group || '')) return sectors
  const without = sectors.filter(sector => sector.id !== dragId)
  const index = without.findIndex(sector => sector.id === targetId)
  if (index < 0) return sectors
  const insertAt = position === 'after' ? index + 1 : index
  const next = [...without]
  next.splice(insertAt, 0, drag)
  return next
}

/**
 * 拖到某行成为它的子项。超过三级、拖到自己的子树里都拒绝并返回原因。
 */
export function reparentPingSector(
  sectors: PingSectorConfig[],
  dragId: string,
  targetId: string,
): { sectors: PingSectorConfig[]; error: string } {
  if (dragId === targetId) return { sectors, error: '不能把项拖到自己身上' }
  const drag = sectors.find(sector => sector.id === dragId)
  const target = sectors.find(sector => sector.id === targetId)
  if (!drag || !target) return { sectors, error: '找不到要移动的项' }
  if (collectSubtreeIds(sectors, dragId).has(targetId)) {
    return { sectors, error: '不能把父项拖进它自己的子项里' }
  }
  const targetDepth = pingNodeDepth(sectors, targetId)
  const height = pingSubtreeHeight(sectors, dragId)
  if (targetDepth + height > PING_MAX_DEPTH) {
    return { sectors, error: `最多 ${PING_MAX_DEPTH} 级菜单；这次拖动会超过限制` }
  }
  const group = childGroupOf(target)
  const nextTarget: PingSectorConfig = {
    ...target,
    kind: 'subring',
    subring: target.subring || group,
  }
  const next = sectors.map(sector => {
    if (sector.id === targetId) return nextTarget
    if (sector.id === dragId) return { ...sector, group }
    return sector
  })
  return { sectors: next, error: '' }
}
