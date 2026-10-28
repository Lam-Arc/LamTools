// user:“第一版就支持多个分屏，左右 / 上下自由组合”+(布局与显示解耦，递归组合任意内容，主区始终没有标签)。
export type SplitEdge = 'left' | 'right' | 'top' | 'bottom'
// user:“支持一下”+(独立插件页面是可持久化、可拖动的分屏标签)。
export type SplitContent = 'page' | 'browser' | 'editor' | 'files' | 'agent' | 'conversation' | 'plugin'
import type { AuxiliaryContext } from '@/auxiliary/workspace'
import { validAuxiliaryContext } from '@/auxiliary/workspace'
// user:“辅助对话”+(侧屏聊天拥有独立会话身份与可恢复的来源引用)。
export interface SplitTab { id: string; kind: SplitContent; title: string; resource: string; sessionId?: string; root?: string; projectId?: string; context?: AuxiliaryContext; modelId?: string; contextSent?: boolean }
export interface SplitPane { id: string; tabs: SplitTab[]; activeTab: string }
export type SplitNode = { type: 'pane'; id: string } | { type: 'split'; id: string; direction: 'columns' | 'rows'; ratio: number; first: SplitNode; second: SplitNode }
export interface SplitState { version: 1; tree: SplitNode; panes: Record<string, SplitPane>; activePane: string; hidden: boolean; focused: string | null }
export interface Rect { x: number; y: number; width: number; height: number }
export interface Divider { id: string; direction: 'columns' | 'rows'; rect: Rect; handle: Rect; parent: Rect; ratio: number }
const GAP = 2
// user:“拖拽的判定，应该只有中间区域是拖拽判定，偏靠角的那一块应该留给创建分屏的判定”+(分隔线只有中段可调整，角部让给角柄拉屏)。
const DIVIDER_HANDLE = 10
const DIVIDER_END_GUARD = 18
// user:“审查分屏代码，并优化”+(标签栏高度只有一个来源，内容区与空状态不再各自硬编码 36px)。
export const SPLIT_TAB_BAR_HEIGHT = 36
// user:“审查分屏代码，并优化”+(同一份内容、同一项目范围才算同一个标签；设置/搜索/插件/账号与项目无关，切换项目后仍复用原标签)。
const GLOBAL_PAGES = new Set(['settings', 'search', 'plugins', 'account'])
export function sameTab(a: SplitTab, b: SplitTab): boolean {
  const sharedScope = a.kind === 'page' && GLOBAL_PAGES.has(a.resource)
  return Boolean(a.resource) && a.kind === b.kind && a.resource === b.resource && a.sessionId === b.sessionId && (sharedScope || a.root === b.root) && (a.kind !== 'plugin' || a.projectId === b.projectId)
}
let sequence = 0
const uid = () => `split-${Date.now().toString(36)}-${++sequence}`
export const newTabId = uid
export function createSplitState(): SplitState { return { version: 1, tree: { type: 'pane', id: 'main' }, panes: {}, activePane: 'main', hidden: false, focused: null } }
export function paneIds(node: SplitNode): string[] { return node.type === 'pane' ? [node.id] : [...paneIds(node.first), ...paneIds(node.second)] }
function replace(node: SplitNode, id: string, replacement: SplitNode): SplitNode {
  if (node.id === id) return replacement
  if (node.type === 'split') { node.first = replace(node.first, id, replacement); node.second = replace(node.second, id, replacement) }
  return node
}
export function splitPane(state: SplitState, target: string, edge: SplitEdge, ratio?: number): string | null {
  if (!paneIds(state.tree).includes(target) || Object.keys(state.panes).length >= 24) return null
  const id = uid(), leaf: SplitNode = { type: 'pane', id }, original: SplitNode = { type: 'pane', id: target }
  const before = edge === 'left' || edge === 'top'
  // user:“拉起其他分屏的时候...通过拖动拉起，而不是点击按钮。就类似 blender”+(拖动距离换算出的分隔比例；非法值回落到默认比例)。
  const share = ratio !== undefined && Number.isFinite(ratio) ? Math.min(.95, Math.max(.05, ratio)) : target === 'main' && edge === 'right' ? .6 : .5
  state.tree = replace(state.tree, target, { type: 'split', id: uid(), direction: edge === 'left' || edge === 'right' ? 'columns' : 'rows', ratio: share, first: before ? leaf : original, second: before ? original : leaf })
  state.panes[id] = { id, tabs: [], activeTab: '' }; state.activePane = id; state.hidden = false; state.focused = null
  return id
}
export function openTab(state: SplitState, pane: string, tab: SplitTab): string | null {
  const target = state.panes[pane]
  if (!target) return null
  const existing = target.tabs.find(open => sameTab(open, tab))
  if (!existing) target.tabs.push(tab)
  target.activeTab = existing?.id ?? tab.id; state.activePane = pane; state.hidden = false
  return target.activeTab
}
function prune(node: SplitNode, id: string): SplitNode | null {
  if (node.type === 'pane') return node.id === id ? null : node
  const a = prune(node.first, id), b = prune(node.second, id)
  if (!a) return b
  if (!b) return a
  node.first = a; node.second = b; return node
}
export function closePane(state: SplitState, id: string) {
  if (id === 'main' || !state.panes[id]) return
  const ids = paneIds(state.tree), index = ids.indexOf(id)
  state.tree = prune(state.tree, id) ?? { type: 'pane', id: 'main' }
  delete state.panes[id]
  if (state.activePane === id) state.activePane = ids[index - 1] || 'main'
  if (state.focused === id) state.focused = null
}
export function closeTab(state: SplitState, pane: string, id: string): boolean {
  const target = state.panes[pane], index = target?.tabs.findIndex(t => t.id === id) ?? -1
  if (!target || index < 0) return false
  target.tabs.splice(index, 1)
  if (target.activeTab === id) target.activeTab = target.tabs[Math.min(index, target.tabs.length - 1)]?.id ?? ''
  if (!target.tabs.length) closePane(state, pane)
  return true
}
export function moveTab(state: SplitState, source: string, target: string, tabId: string) {
  if (source === target) return
  const from = state.panes[source], to = state.panes[target]
  const tab = from?.tabs.find(t => t.id === tabId)
  if (!from || !to || !tab) return
  // user:“审查分屏代码，并优化”+(目标屏已有同一内容时移动等于合并：保留原标签身份，不复制第二份)。
  const existing = to.tabs.find(open => sameTab(open, tab))
  const index = from.tabs.indexOf(tab)
  from.tabs.splice(index, 1)
  if (from.activeTab === tabId) from.activeTab = from.tabs[Math.min(index, from.tabs.length - 1)]?.id ?? ''
  if (!from.tabs.length) closePane(state, source)
  if (existing) to.activeTab = existing.id
  else { to.tabs.push(tab); to.activeTab = tab.id }
  state.activePane = target
}
// user:“该对齐的就全部都去对齐”“我要体验一致化”+(角拖合并、边框合并/交换与 Blender 保持同一套体验)。
function siblingSplit(node: SplitNode, a: string, b: string): SplitNode | null {
  if (node.type !== 'split') return null
  if (node.first.type === 'pane' && node.second.type === 'pane'
    && ((node.first.id === a && node.second.id === b) || (node.first.id === b && node.second.id === a))) return node
  return siblingSplit(node.first, a, b) || siblingSplit(node.second, a, b)
}
export function canJoinPanes(tree: SplitNode, a: string, b: string): boolean {
  return a !== b && a !== 'main' && b !== 'main' && Boolean(siblingSplit(tree, a, b))
}
export function joinPanes(state: SplitState, a: string, b: string): boolean {
  if (!canJoinPanes(state.tree, a, b) || !state.panes[a] || !state.panes[b]) return false
  const target = b, source = a, targetPane = state.panes[target], sourcePane = state.panes[source]
  function collapse(node: SplitNode): SplitNode {
    if (node.type === 'pane') return node
    if (node.first.type === 'pane' && node.second.type === 'pane'
      && ((node.first.id === a && node.second.id === b) || (node.first.id === b && node.second.id === a))) return { type: 'pane', id: target }
    node.first = collapse(node.first); node.second = collapse(node.second); return node
  }
  state.tree = collapse(state.tree)
  for (const tab of sourcePane.tabs) if (!targetPane.tabs.some(open => sameTab(open, tab))) targetPane.tabs.push(tab)
  if (!targetPane.tabs.some(tab => tab.id === targetPane.activeTab)) targetPane.activeTab = targetPane.tabs[0]?.id ?? ''
  delete state.panes[source]
  if (state.activePane === source) state.activePane = target
  if (state.focused === source) state.focused = target
  return true
}
export function swapPanes(state: SplitState, a: string, b: string): boolean {
  const first = state.panes[a], second = state.panes[b]
  if (!first || !second || a === b) return false
  const tabs = first.tabs; first.tabs = second.tabs; second.tabs = tabs
  const active = first.activeTab; first.activeTab = second.activeTab; second.activeTab = active
  return true
}
export function minimumSize(node: SplitNode): { width: number; height: number } {  if (node.type === 'pane') return node.id === 'main' ? { width: 420, height: 320 } : { width: 320, height: 240 }
  const a = minimumSize(node.first), b = minimumSize(node.second)
  return node.direction === 'columns' ? { width: a.width + b.width + GAP, height: Math.max(a.height, b.height) } : { width: Math.max(a.width, b.width), height: a.height + b.height + GAP }
}
export function canFitSplit(tree: SplitNode, target: string, edge: SplitEdge, width: number, height: number): boolean {
  if (!paneIds(tree).includes(target)) return false
  const copy = JSON.parse(JSON.stringify(tree)) as SplitNode
  const leaf: SplitNode = { type: 'pane', id: target }
  const prospective = replace(copy, target, { type: 'split', id: 'prospective-split', direction: edge === 'left' || edge === 'right' ? 'columns' : 'rows', ratio: .5, first: leaf, second: { type: 'pane', id: 'prospective-pane' } })
  const min = minimumSize(prospective)
  return min.width <= width && min.height <= height
}
export function resizeSplit(node: SplitNode, id: string, ratio: number, extent: number) {
  if (node.type !== 'split') return
  if (node.id === id) {
    const key = node.direction === 'columns' ? 'width' : 'height', usable = Math.max(1, extent - GAP)
    const lo = minimumSize(node.first)[key] / usable, hi = 1 - minimumSize(node.second)[key] / usable
    node.ratio = lo <= hi ? Math.max(lo, Math.min(hi, ratio)) : .5
  } else { resizeSplit(node.first, id, ratio, extent); resizeSplit(node.second, id, ratio, extent) }
}
export function layoutRects(tree: SplitNode, bounds: Rect): { panes: Record<string, Rect>; dividers: Divider[] } {
  const panes: Record<string, Rect> = {}, dividers: Divider[] = []
  function walk(node: SplitNode, rect: Rect) {
    if (node.type === 'pane') { panes[node.id] = rect; return }
    const columns = node.direction === 'columns', extent = Math.max(0, (columns ? rect.width : rect.height) - GAP)
    const key = columns ? 'width' : 'height', minA = minimumSize(node.first)[key], minB = minimumSize(node.second)[key]
    const part = extent >= minA + minB ? Math.max(minA, Math.min(extent - minB, Math.round(extent * node.ratio))) : Math.round(extent * node.ratio)
    const a = { ...rect, [key]: part }, b = { ...rect, [key]: extent - part, [columns ? 'x' : 'y']: (columns ? rect.x : rect.y) + part + GAP }
    const divider = columns ? { x: rect.x + part, y: rect.y, width: GAP, height: rect.height } : { x: rect.x, y: rect.y + part, width: rect.width, height: GAP }
    const handle = columns
      ? { x: divider.x - (DIVIDER_HANDLE - GAP) / 2, y: divider.y + SPLIT_TAB_BAR_HEIGHT + 8, width: DIVIDER_HANDLE, height: Math.max(0, divider.height - SPLIT_TAB_BAR_HEIGHT - 8 - DIVIDER_END_GUARD) }
      : { x: divider.x + DIVIDER_END_GUARD, y: divider.y - (DIVIDER_HANDLE - GAP) / 2, width: Math.max(0, divider.width - DIVIDER_END_GUARD * 2), height: DIVIDER_HANDLE }
    dividers.push({ id: node.id, direction: node.direction, rect: divider, handle, parent: rect, ratio: node.ratio })
    walk(node.first, a); walk(node.second, b)
  }
  walk(tree, bounds); return { panes, dividers }
}
export function arrangeLayout(state: SplitState, preset: 'columns' | 'rows' | 'main-right' | 'grid') {
  const ids = paneIds(state.tree).filter(id => id !== 'main'), count = preset === 'grid' ? 3 : preset === 'main-right' ? 2 : 1
  while (ids.length < count) { const id = uid(); state.panes[id] = { id, tabs: [], activeTab: '' }; ids.push(id) }
  // user:“审查分屏代码，并优化”+(预设把多块屏并成一块时沿用同一标签身份，不再留下两份相同内容)。
  for (const id of ids.slice(count)) {
    const target = state.panes[ids[count - 1]]
    for (const tab of state.panes[id].tabs) if (!target.tabs.some(open => sameTab(open, tab))) target.tabs.push(tab)
    delete state.panes[id]
  }
  for (const pane of Object.values(state.panes)) if (!pane.tabs.some(t => t.id === pane.activeTab)) pane.activeTab = pane.tabs[0]?.id ?? ''
  const leaf = (id: string): SplitNode => ({ type: 'pane', id })
  const branch = (direction: 'columns' | 'rows', first: SplitNode, second: SplitNode): SplitNode => ({ type: 'split', id: uid(), direction, ratio: .5, first, second })
  state.tree = preset === 'grid' ? branch('columns', branch('rows', leaf('main'), leaf(ids[0])), branch('rows', leaf(ids[1]), leaf(ids[2])))
    : preset === 'main-right' ? branch('columns', leaf('main'), branch('rows', leaf(ids[0]), leaf(ids[1])))
    : branch(preset, leaf('main'), leaf(ids[0]))
  state.activePane = 'main'; state.hidden = false; state.focused = null
}
export function restoreSplitState(raw: string | null): SplitState {
  try {
    const state = JSON.parse(raw || '') as SplitState
    if (state.version !== 1 || !state.panes || typeof state.panes !== 'object' || Array.isArray(state.panes)) throw Error()
    const seen = new Set<string>(), tabIds = new Set<string>(); let nodes = 0
    function validate(node: SplitNode, depth = 0) {
      // user:“审查分屏代码，并优化”+(最多 24 块辅助屏可形成 23 层深链，深度上限必须覆盖合法布局，只拦截失控递归)。
      if (!node || depth > 32 || ++nodes > 49 || typeof node.id !== 'string' || seen.has(node.id)) throw Error()
      seen.add(node.id)
      if (node.type === 'pane') {
        if (node.id === 'main') return
        const pane = state.panes[node.id]
        // user:“审查分屏代码，并优化”+(面板 id、活动标签和标签 id 必须自洽，损坏数据整份丢弃而不是错位显示)。
        if (!pane || pane.id !== node.id || !Array.isArray(pane.tabs) || pane.tabs.length > 100 || typeof pane.activeTab !== 'string') throw Error()
        for (const t of pane.tabs) {
          if (t?.kind === 'conversation' && ((t.context !== undefined && !validAuxiliaryContext(t.context)) || (t.modelId !== undefined && typeof t.modelId !== 'string') || (t.contextSent !== undefined && typeof t.contextSent !== 'boolean'))) throw Error()
          if (!t || !t.id || !['page','browser','editor','files','agent','conversation','plugin'].includes(t.kind) || ![t.id,t.resource,t.title].every(v => typeof v === 'string') || tabIds.has(t.id) || (t.root !== undefined && typeof t.root !== 'string') || (t.projectId !== undefined && typeof t.projectId !== 'string') || (t.sessionId !== undefined && typeof t.sessionId !== 'string')) throw Error()
          tabIds.add(t.id)
        }
        if (!pane.tabs.some(t => t.id === pane.activeTab)) pane.activeTab = pane.tabs[0]?.id ?? ''
      } else if (node.type === 'split' && ['rows','columns'].includes(node.direction) && Number.isFinite(node.ratio) && node.ratio > 0 && node.ratio < 1) {
        validate(node.first, depth + 1); validate(node.second, depth + 1)
      } else throw Error()
    }
    validate(state.tree)
    const ids = paneIds(state.tree)
    if (!ids.includes('main')) throw Error()
    for (const id of Object.keys(state.panes)) if (!ids.includes(id) || id === 'main') delete state.panes[id]
    state.activePane = ids.includes(state.activePane) ? state.activePane : 'main'
    state.focused = state.focused && ids.includes(state.focused) ? state.focused : null
    state.hidden = Boolean(state.hidden)
    return state
  } catch { return createSplitState() }
}
