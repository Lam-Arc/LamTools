<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { BookOpen, FileText, FolderTree, Globe, PanelLeftClose, PanelTopClose, Columns2, Rows2, Maximize2, X, LayoutGrid, Image as ImageIcon } from 'lucide-vue-next'
import CoreSplitPane from './CoreSplitPane.vue'
import { openContextMenu } from './context-menu/context-menu'
import type { ContextMenuEntry } from './context-menu/types'
import { layoutRects, minimumSize, moveTab, resizeSplit, SPLIT_TAB_BAR_HEIGHT, canJoinPanes, type Divider, type Rect, type SplitContent, type SplitEdge, type SplitTab } from '@/split/layout'
import type { SplitWorkspaceController } from '@/split/useSplitWorkspace'
import { t } from '@/i18n'
import '@/styles/split-workspace.css'
import { useAuxiliaryWorkspace } from '@/auxiliary/workspace'
import { contributionState, contributionsRpc, ensureContributions } from '@/plugins/contributions'
const auxiliary = useAuxiliaryWorkspace()
const props = defineProps<{ controller: SplitWorkspaceController; workRoot: string; dirty?: Set<string> }>()
const emit = defineEmits<{ geometry: [style: Record<string, string>]; visibility: [id: string, visible: boolean] }>()
const root = ref<HTMLElement | null>(null), size = ref({ width: 0, height: 0 }), drop = ref<{ pane: string; edge: SplitEdge | 'center' } | null>(null)
const state = props.controller.state
const bounds = computed(() => ({ x: 0, y: 0, ...size.value }))
const normal = computed(() => layoutRects(state.tree, bounds.value))
const cramped = computed(() => { const min = minimumSize(state.tree); return size.value.width > 0 && (min.width > size.value.width || min.height > size.value.height) })
const focused = computed(() => state.hidden ? 'main' : state.focused || (cramped.value ? state.activePane : null))
const geometry = computed(() => {
  const main = focused.value ? focused.value === 'main' ? bounds.value : { x: 0, y: 0, width: 0, height: 0 } : normal.value.panes.main
  const left = main.x === 0, top = main.y === 0, right = main.x + main.width >= size.value.width - 1, bottom = main.y + main.height >= size.value.height - 1
  const inner = 'var(--workspace-panel-radius-inner)', outer = 'var(--workspace-panel-radius-outer)'
  return { '--split-primary-x': `${main.x}px`, '--split-primary-y': `${main.y}px`, '--split-primary-width': `${main.width}px`, '--split-primary-height': `${main.height}px`, '--split-primary-bottom': `${size.value.height - main.y - main.height}px`, '--split-primary-visible': main.width ? 'visible' : 'hidden', '--split-primary-radius': `${left && top ? inner : '0px'} ${right && top ? outer : '0px'} ${right && bottom ? outer : '0px'} ${left && bottom ? inner : '0px'}` }
})
watch(geometry, value => emit('geometry', value), { immediate: true })
const activeRect = (pane: string): Rect => focused.value === pane ? bounds.value : normal.value.panes[pane] || bounds.value
const paneVisible = (pane: string) => !state.hidden && (!focused.value || focused.value === pane)
const css = (rect: Rect, content = false) => ({ left: `${rect.x}px`, top: `${rect.y + (content ? SPLIT_TAB_BAR_HEIGHT : 0)}px`, width: `${rect.width}px`, height: `${Math.max(0, rect.height - (content ? SPLIT_TAB_BAR_HEIGHT : 0))}px` })
// user:“拖拽的判定，应该只有中间区域是拖拽判定，偏靠角的那一块应该留给创建分屏的判定”+(分隔线视觉仍贯通，但只有中间那一截接收拖动)。
const dividerStyle = (divider: Divider) => ({
  ...css(divider.handle),
  '--divider-extend-top': `${Math.max(0, divider.handle.y - divider.rect.y)}px`,
  '--divider-extend-bottom': `${Math.max(0, divider.rect.y + divider.rect.height - divider.handle.y - divider.handle.height)}px`,
  '--divider-extend-left': `${Math.max(0, divider.handle.x - divider.rect.x)}px`,
  '--divider-extend-right': `${Math.max(0, divider.rect.x + divider.rect.width - divider.handle.x - divider.handle.width)}px`,
})
const allTabs = props.controller.tabs
const tabVisible = (pane: string, tab: SplitTab) => paneVisible(pane) && state.panes[pane]?.activeTab === tab.id
// user:“审查分屏代码，并优化”+(可见性事件只报告真正变化的标签，避免每次布局变化都通知所有网页和插件页面)。
const reportedVisibility = new Map<string, boolean>()
watch(() => allTabs.value.map(({ pane, tab }) => [tab.id, tabVisible(pane, tab)] as const), list => {
  const live = new Set<string>()
  for (const [id, visible] of list) {
    live.add(id)
    if (reportedVisibility.get(id) !== visible) { reportedVisibility.set(id, visible); emit('visibility', id, visible) }
  }
  for (const id of [...reportedVisibility.keys()]) if (!live.has(id)) reportedVisibility.delete(id)
}, { immediate: true })
function canSplit(pane: string, edge: SplitEdge) {
  return props.controller.canSplit(pane, edge)
}
function openMenu(event: MouseEvent, pane: string) {
  const add = (kind: 'page' | 'browser' | 'editor' | 'preview' | 'files', resource: string, title: string) => () => { props.controller.add(kind, resource, title, pane) }
  const pages = contributionState().pages
  const pluginItems: ContextMenuEntry[] = pages.length ? [{ type: 'submenu', label: t('插件页面'), children: pages.map(page => ({
    label: `${page.title} · ${page.plugin}`, action: () => { props.controller.openPluginPage(page, pane) },
  })) }] : []
  openContextMenu({ event, ariaLabel: t('打开内容'), items: [
    // user:“尽可能的复用能力”+(打开辅助会话的菜单动作仅负责执行，不把新标签当成动作返回值)。
    { label: t('辅助对话'), action: () => { auxiliary?.open(undefined, pane) } },
    { label: t('资料库'), icon: BookOpen, action: add('page', 'library', t('资料库')) },
    { label: t('设置'), action: add('page', 'settings', t('设置')) },
    { label: t('定时任务'), action: add('page', 'arrange', t('定时任务')) },
    { label: t('插件'), action: add('page', 'plugins', t('插件')) },
    ...pluginItems,
    { type: 'separator' },
    { label: t('浏览器'), icon: Globe, action: add('browser', '', t('浏览器')) },
    { label: t('文本编辑器'), icon: FileText, action: add('editor', '', t('未命名')) },
    { label: t('文件预览'), icon: ImageIcon, action: add('preview', '', t('文件预览')) },
    { label: t('文件树'), icon: FolderTree, action: add('files', props.workRoot, t('文件')) },
  ] })
}
function splitContentItems(pane: string, edge: SplitEdge): ContextMenuEntry[] {
  const create = (kind: SplitContent, resource = '', title = '') => () => {
    const target = props.controller.splitAt(pane, edge)
    if (target) props.controller.add(kind, resource, title, target)
  }
  const pages = contributionState().pages
  return [
    { label: t('辅助对话'), action: () => { const target = props.controller.splitAt(pane, edge); if (target) auxiliary?.open(undefined, target) } },
    { label: t('资料库'), icon: BookOpen, action: create('page', 'library', t('资料库')) },
    { label: t('设置'), action: create('page', 'settings', t('设置')) },
    { label: t('定时任务'), action: create('page', 'arrange', t('定时任务')) },
    { label: t('插件'), action: create('page', 'plugins', t('插件')) },
    ...(pages.length ? [{ type: 'submenu' as const, label: t('插件页面'), children: pages.map(page => ({
      label: `${page.title} · ${page.plugin}`, action: () => { const target = props.controller.splitAt(pane, edge); if (target) props.controller.openPluginPage(page, target) },
    })) }] : []),
    { type: 'separator' as const },
    { label: t('浏览器'), icon: Globe, action: create('browser', '', t('浏览器')) },
    { label: t('文本编辑器'), icon: FileText, action: create('editor', '', t('未命名')) },
    { label: t('文件预览'), icon: ImageIcon, action: create('preview', '', t('文件预览')) },
    { label: t('文件树'), icon: FolderTree, action: create('files', props.workRoot, t('文件')) },
  ]
}
function operations(event: MouseEvent, pane = state.activePane) {
  props.controller.activate(pane)
  const items: ContextMenuEntry[] = [
    { label: t('辅助对话'), action: () => auxiliary?.open(undefined, pane === 'main' ? undefined : pane) },
    { type: 'submenu', label: t('向右分屏'), icon: Columns2, disabled: !canSplit(pane, 'right'), children: splitContentItems(pane, 'right') },
    { type: 'submenu', label: t('向下分屏'), icon: Rows2, disabled: !canSplit(pane, 'bottom'), children: splitContentItems(pane, 'bottom') },
    { label: t('打开内容…'), action: () => { if (pane === 'main') { const id = props.controller.split('main', 'right'); if (id) openMenu(event, id) } else openMenu(event, pane) } },
    { type: 'separator' },
    { type: 'submenu', label: t('布局'), icon: LayoutGrid, children: [
      { label: t('两列'), action: () => props.controller.preset('columns') }, { label: t('两行'), action: () => props.controller.preset('rows') },
      { label: t('左主右双'), action: () => props.controller.preset('main-right') }, { label: t('四格'), action: () => props.controller.preset('grid') },
    ] },
    { label: state.focused === pane ? t('退出聚焦') : t('聚焦当前屏'), icon: Maximize2, action: () => props.controller.focus(pane) },
  ]
  // user:“审查分屏代码，并优化”+(还没有分屏时不能出现“收起分屏”，否则点它会反而新建一块空屏)。
  if (Object.keys(state.panes).length) items.push({ label: state.hidden ? t('恢复分屏') : t('收起分屏'), icon: PanelLeftClose, action: () => props.controller.toggle() })
  if (pane !== 'main') items.push({ type: 'separator' }, { label: t('关闭当前屏'), icon: X, action: () => props.controller.closePane(pane) })
  openContextMenu({ event, items, ariaLabel: t('分屏') })
}
function tabMenu(event: MouseEvent, pane: string, tab: SplitTab) {
  openContextMenu({ event, ariaLabel: t('标签操作'), items: [
    ...(['right', 'bottom'] as SplitEdge[]).map(edge => ({ label: edge === 'right' ? t('移到右侧新分屏') : t('移到下方新分屏'), disabled: !canSplit(pane, edge), action: () => { const id = props.controller.split(pane, edge); if (id) moveTab(state, pane, id, tab.id) } })),
    ...Object.keys(state.panes).filter(id => id !== pane).map((id, index) => ({ label: t('移到分屏 {0}', { 0: index + 1 }), action: () => moveTab(state, pane, id, tab.id) })),
    { type: 'separator' as const }, { label: t('关闭标签'), action: () => props.controller.closeTab(pane, tab) },
  ] })
}
// user:“包括显示表现最好也对齐”“我要体验一致化”+(边框右键合并/交换相邻分屏，和 Blender 的 Area Options 一样提供非拖拽入口)。
function adjacentPanes(event: MouseEvent, divider: Divider): [string, string] | null {
  const box = root.value?.getBoundingClientRect()
  if (!box) return null
  const x = event.clientX - box.left, y = event.clientY - box.top
  const panes = Object.entries(normal.value.panes).filter(([id]) => id !== 'main' && state.panes[id])
  const near = (value: number, target: number) => Math.abs(value - target) <= 1
  if (divider.direction === 'columns') {
    const left = panes.filter(([, rect]) => near(rect.x + rect.width, divider.rect.x) && y >= rect.y && y <= rect.y + rect.height).sort((a, b) => b[1].x - a[1].x)[0]?.[0]
    const right = panes.filter(([, rect]) => near(rect.x, divider.rect.x + divider.rect.width) && y >= rect.y && y <= rect.y + rect.height).sort((a, b) => a[1].x - b[1].x)[0]?.[0]
    return left && right ? [left, right] : null
  }
  const top = panes.filter(([, rect]) => near(rect.y + rect.height, divider.rect.y) && x >= rect.x && x <= rect.x + rect.width).sort((a, b) => b[1].y - a[1].y)[0]?.[0]
  const bottom = panes.filter(([, rect]) => near(rect.y, divider.rect.y + divider.rect.height) && x >= rect.x && x <= rect.x + rect.width).sort((a, b) => a[1].y - b[1].y)[0]?.[0]
  return top && bottom ? [top, bottom] : null
}
function dividerMenu(event: MouseEvent, divider: Divider) {
  const pair = adjacentPanes(event, divider)
  if (!pair) return
  const [first, second] = pair
  openContextMenu({ event, ariaLabel: t('分屏边界'), items: [
    { label: t('合并这两块分屏'), disabled: !canJoinPanes(state.tree, first, second), action: () => { props.controller.join(first, second) } },
    { label: t('交换这两块分屏'), action: () => { props.controller.swap(first, second) } },
  ] })
}
const drag = ref<{ pane: string; tab: string } | null>(null)
function dragStart(event: DragEvent, pane: string, tab: SplitTab) { drag.value = { pane, tab: tab.id }; document.body.classList.add('split-is-dragging'); event.dataTransfer?.setData('application/x-lamtools-split-tab', JSON.stringify(drag.value)); if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move' }
function dragOver(event: DragEvent, pane: string) {
  if (!drag.value) return
  const rect = activeRect(pane), box = root.value!.getBoundingClientRect(), x = event.clientX - box.left - rect.x, y = event.clientY - box.top - rect.y
  let edge: SplitEdge | 'center' = x < rect.width * .22 ? 'left' : x > rect.width * .78 ? 'right' : y < rect.height * .22 ? 'top' : y > rect.height * .78 ? 'bottom' : 'center'
  if (edge === 'center' && pane === 'main') edge = 'right'
  if (edge !== 'center' && !canSplit(pane, edge)) { drop.value = null; return }
  event.preventDefault(); drop.value = { pane, edge }
}
function onDrop(event: DragEvent) {
  event.preventDefault()
  if (drag.value && drop.value) {
    const { pane, edge } = drop.value
    if (edge === 'center') moveTab(state, drag.value.pane, pane, drag.value.tab)
    else { const id = props.controller.split(pane, edge); if (id) moveTab(state, drag.value.pane, id, drag.value.tab) }
  }
  endDrag()
}
function endDrag() { drag.value = null; drop.value = null; document.body.classList.remove('split-is-dragging') }
// user:“它绝对不是在分的时候先给你出来一个遮罩，然后告诉你什么‘向上分屏’、‘向右分屏’，而是直接就像拉出来了一个新分屏”+(预览直接描出分割后的两块区域和分隔线，不显示文字/遮罩)。
type SplitPreviewMode = 'split' | 'merge' | 'join'
interface SplitPreviewModel { mode: SplitPreviewMode; areas: Rect[]; line?: Rect }
const PREVIEW_GAP = 2
function splitAreas(source: Rect, edge: SplitEdge, size: number): SplitPreviewModel {
  const horizontal = edge === 'left' || edge === 'right', extent = horizontal ? source.width : source.height
  const created = Math.max(0, Math.min(extent, Math.round(size))), existing = Math.max(0, extent - created - PREVIEW_GAP)
  const next: Rect = edge === 'left' ? { x: source.x, y: source.y, width: created, height: source.height }
    : edge === 'right' ? { x: source.x + existing + PREVIEW_GAP, y: source.y, width: created, height: source.height }
    : edge === 'top' ? { x: source.x, y: source.y, width: source.width, height: created }
    : { x: source.x, y: source.y + existing + PREVIEW_GAP, width: source.width, height: created }
  const keep: Rect = edge === 'left' ? { x: source.x + created + PREVIEW_GAP, y: source.y, width: existing, height: source.height }
    : edge === 'right' ? { x: source.x, y: source.y, width: existing, height: source.height }
    : edge === 'top' ? { x: source.x, y: source.y + created + PREVIEW_GAP, width: source.width, height: existing }
    : { x: source.x, y: source.y, width: source.width, height: existing }
  const line: Rect = edge === 'left' ? { x: source.x + created, y: source.y, width: PREVIEW_GAP, height: source.height }
    : edge === 'right' ? { x: source.x + existing, y: source.y, width: PREVIEW_GAP, height: source.height }
    : edge === 'top' ? { x: source.x, y: source.y + created, width: source.width, height: PREVIEW_GAP }
    : { x: source.x, y: source.y + existing, width: source.width, height: PREVIEW_GAP }
  return { mode: 'split', areas: [next, keep], line }
}
const joinTarget = ref<{ source: string; target: string } | null>(null)
function dropPreview(): SplitPreviewModel | null {
  if (!drop.value) return null
  const source = activeRect(drop.value.pane)
  if (drop.value.edge === 'center') return { mode: 'merge', areas: [source] }
  const horizontal = drop.value.edge === 'left' || drop.value.edge === 'right', extent = horizontal ? source.width : source.height
  return splitAreas(source, drop.value.edge, Math.round((extent - PREVIEW_GAP) / 2))
}
function pullPreview(): SplitPreviewModel | null {
  if (!pull.value) return null
  const source = activeRect(pull.value.pane), horizontal = pull.value.edge === 'left' || pull.value.edge === 'right'
  return splitAreas(source, pull.value.edge, horizontal ? pull.value.rect.width : pull.value.rect.height)
}
const preview = computed<SplitPreviewModel | null>(() => joinTarget.value ? { mode: 'join', areas: [activeRect(joinTarget.value.source), activeRect(joinTarget.value.target)] } : pullPreview() || dropPreview())
// user:“分割线位置跟着鼠标...分割线方向按主拖动轴，起始角决定新区域落在哪一侧”+(Blender 式角柄：从哪个角起拖，新屏就贴着那个角；指针位置决定分隔线位置)。
type SplitCorner = 'top-left' | 'bottom-left' | 'bottom-right'
const CORNER_SIZE = 18
const pull = ref<{ pane: string; edge: SplitEdge; rect: Rect; ratio: number } | null>(null)
let stopPull: (() => void) | undefined
function clampSplitShare(pane: string, edge: SplitEdge, share: number, extent: number) {
  const key = edge === 'left' || edge === 'right' ? 'width' : 'height'
  const existing = minimumSize({ type: 'pane', id: pane })[key], created = minimumSize({ type: 'pane', id: '__new-split' })[key]
  const lo = created / extent, hi = 1 - existing / extent
  return lo <= hi ? Math.max(lo, Math.min(hi, share)) : .5
}
function beginSplitPull(event: PointerEvent, pane: string, corner: SplitCorner) {
  if (event.button !== 0) return
  stopPull?.()
  event.preventDefault()
  const handle = event.currentTarget as HTMLElement, source = { ...activeRect(pane) }
  const startX = event.clientX, startY = event.clientY
  let moved = false
  const stop = () => {
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', finish)
    window.removeEventListener('pointercancel', cancel); window.removeEventListener('keydown', cancelKey)
    handle.removeEventListener('lostpointercapture', cancel)
    if (handle.hasPointerCapture?.(event.pointerId)) handle.releasePointerCapture(event.pointerId)
    document.body.classList.remove('split-is-pulling')
    pull.value = null; joinTarget.value = null; stopPull = undefined
  }
  const move = (e: PointerEvent) => {
    const dx = e.clientX - startX, dy = e.clientY - startY
    if (!moved && Math.hypot(dx, dy) < 6) return
    moved = true
    // Hide native webviews as soon as the gesture leaves the grip so the pointer can cross other panes.
    document.body.classList.add('split-is-pulling')
    const box = root.value?.getBoundingClientRect()
    if (!box) return
    const x = e.clientX - box.left, y = e.clientY - box.top
    if (!state.focused && !state.hidden) {
      const target = Object.entries(normal.value.panes).find(([id, rect]) => id !== 'main' && state.panes[id] && x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height)?.[0]
      if (target && target !== pane && canJoinPanes(state.tree, pane, target)) { joinTarget.value = { source: pane, target }; pull.value = null; return }
    }
    joinTarget.value = null
    if (x < source.x || x >= source.x + source.width || y < source.y || y >= source.y + source.height) { pull.value = null; return }
    const columns = Math.abs(dx) >= Math.abs(dy)
    const edge: SplitEdge = columns ? (corner.endsWith('left') ? 'left' : 'right') : (corner.startsWith('top') ? 'top' : 'bottom')
    if (!canSplit(pane, edge)) { pull.value = null; return }
    const extent = Math.max(1, columns ? source.width : source.height)
    const pointer = columns ? x : y, start = columns ? source.x : source.y
    const nextSize = edge === 'left' || edge === 'top' ? pointer - start : start + extent - pointer
    if (nextSize < 8) { pull.value = null; return }
    const share = clampSplitShare(pane, edge, nextSize / extent, extent), size = Math.round(extent * share)
    const ratio = edge === 'left' || edge === 'top' ? share : 1 - share
    const rect = edge === 'left' ? { x: source.x, y: source.y, width: size, height: source.height }
      : edge === 'right' ? { x: source.x + source.width - size, y: source.y, width: size, height: source.height }
      : edge === 'top' ? { x: source.x, y: source.y, width: source.width, height: size }
      : { x: source.x, y: source.y + source.height - size, width: source.width, height: size }
    pull.value = { pane, edge, rect, ratio }
  }
  const finish = () => {
    const join = joinTarget.value, dropped = pull.value
    stop()
    if (join) props.controller.join(join.source, join.target)
    else if (dropped) props.controller.splitAt(dropped.pane, dropped.edge, dropped.ratio)
  }
  const cancel = () => stop()
  const cancelKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); stop() } }
  stopPull = stop
  try { handle.setPointerCapture?.(event.pointerId) } catch { /* Synthetic or already-released pointers still drag via window listeners. */ }
  handle.addEventListener('lostpointercapture', cancel)
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', finish)
  window.addEventListener('pointercancel', cancel); window.addEventListener('keydown', cancelKey)
}
function cornerStyle(pane: string, corner: 'bottom-left' | 'bottom-right') {
  const rect = activeRect(pane)
  return { left: `${corner === 'bottom-left' ? rect.x : rect.x + rect.width - CORNER_SIZE}px`, top: `${rect.y + rect.height - CORNER_SIZE}px`, width: `${CORNER_SIZE}px`, height: `${CORNER_SIZE}px`, bottom: 'auto' }
}
// user:“相比把全部能力都缝在一个按键里面”+(新屏用短促的淡入和轻微缩放出现，避免突然替换画面)。
const entering = ref(new Set<string>()), knownPanes = new Set(Object.keys(state.panes))
let enterTimer: ReturnType<typeof setTimeout> | undefined
watch(() => Object.keys(state.panes), ids => {
  const added = ids.filter(id => !knownPanes.has(id))
  for (const id of ids) knownPanes.add(id)
  for (const id of [...knownPanes]) if (!ids.includes(id)) knownPanes.delete(id)
  if (!added.length) return
  entering.value = new Set([...entering.value, ...added])
  clearTimeout(enterTimer)
  enterTimer = setTimeout(() => { entering.value = new Set() }, 200)
})
const resizing = ref<string | null>(null)
let stopResize: (() => void) | undefined
function resize(event: PointerEvent, divider: Divider) {
  if (event.button !== 0) return
  // user:“样式优化：动画、交互体验、圆角策略等”+(拖动即时跟手，Esc 撤回本次调整，离开工作区时释放捕获和监听)。
  stopResize?.()
  event.preventDefault(); const el = event.currentTarget as HTMLElement; el.setPointerCapture?.(event.pointerId)
  const original = divider.ratio
  const move = (e: PointerEvent) => {
    const box = root.value!.getBoundingClientRect(), columns = divider.direction === 'columns'
    const extent = columns ? divider.parent.width : divider.parent.height
    const offset = columns ? e.clientX - box.left - divider.parent.x : e.clientY - box.top - divider.parent.y
    let ratio = offset / (extent - 2)
    if (e.ctrlKey) ratio = Math.round(ratio * 12) / 12
    resizeSplit(state.tree, divider.id, ratio, extent)
  }
  const cancel = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); resizeSplit(state.tree, divider.id, original, divider.direction === 'columns' ? divider.parent.width : divider.parent.height); stop() } }
  const stop = () => {
    el.removeEventListener('pointermove', move); el.removeEventListener('pointerup', stop); el.removeEventListener('pointercancel', stop); el.removeEventListener('lostpointercapture', stop)
    window.removeEventListener('keydown', cancel)
    if (el.hasPointerCapture?.(event.pointerId)) el.releasePointerCapture(event.pointerId)
    document.body.classList.remove('split-is-resizing', 'split-resize-columns', 'split-resize-rows'); resizing.value = null; stopResize = undefined
  }
  stopResize = stop; resizing.value = divider.id
  el.addEventListener('pointermove', move); el.addEventListener('pointerup', stop); el.addEventListener('pointercancel', stop); el.addEventListener('lostpointercapture', stop); window.addEventListener('keydown', cancel)
  document.body.classList.add('split-is-resizing', `split-resize-${divider.direction}`)
}
function keyResize(event: KeyboardEvent, divider: Divider) {
  const columns = divider.direction === 'columns', keys = columns ? ['ArrowLeft','ArrowRight'] : ['ArrowUp','ArrowDown']
  if (!keys.includes(event.key) && event.key !== 'Home') return
  event.preventDefault(); resizeSplit(state.tree, divider.id, event.key === 'Home' ? .5 : divider.ratio + (event.key === keys[0] ? -.02 : .02), columns ? divider.parent.width : divider.parent.height)
}
function switchScreen(event: MouseEvent) {
  openContextMenu({ event, items: ['main', ...Object.keys(state.panes)].map((id, i) => ({ label: id === 'main' ? t('主界面') : state.panes[id].tabs.find(t => t.id === state.panes[id].activeTab)?.title || t('分屏 {0}', { 0: i }), checked: (focused.value || state.activePane) === id, action: () => { state.activePane = id; if (state.focused) state.focused = id } })) })
}
let observer: ResizeObserver | undefined
function measure() { const rect = root.value?.getBoundingClientRect(); if (rect) { size.value = { width: rect.width, height: rect.height }; props.controller.setBounds(rect.width, rect.height) } }
onMounted(() => { const rpc = contributionsRpc(); if (rpc) void ensureContributions(rpc); measure(); if (typeof ResizeObserver !== 'undefined') { observer = new ResizeObserver(measure); observer.observe(root.value!) } window.addEventListener('resize', measure); window.addEventListener('dragend', endDrag); window.addEventListener('keydown', cancelDrag) })
function cancelDrag(e: KeyboardEvent) { if (e.key === 'Escape') endDrag() }
onBeforeUnmount(() => { stopResize?.(); stopPull?.(); clearTimeout(enterTimer); endDrag(); observer?.disconnect(); window.removeEventListener('resize', measure); window.removeEventListener('dragend', endDrag); window.removeEventListener('keydown', cancelDrag) })
defineExpose({ operations, openMenu, measure })
</script>
<template>
  <div ref="root" class="split-workspace" data-ui-id="shell.split" :class="{ 'split-workspace--open': Object.keys(state.panes).length > 0 }" :style="{ '--split-tabbar-height': `${SPLIT_TAB_BAR_HEIGHT}px` }" data-region="split" @drop="onDrop">
    <div v-if="drag" class="split-main-drop" :style="css(activeRect('main'))" @dragover="dragOver($event, 'main')"></div>
    <section v-for="pane in state.panes" :key="pane.id" v-show="paneVisible(pane.id)" class="split-pane-frame" :class="{ 'is-entering': entering.has(pane.id), 'is-pulling': pull?.pane === pane.id }" :style="css(activeRect(pane.id))" :aria-label="t('分屏')" @pointerdown="controller.activate(pane.id)" @dragover="dragOver($event, pane.id)">
      <CoreSplitPane :pane="pane" :active="state.activePane === pane.id" :dirty="dirty" @focus="controller.activate(pane.id)" @activate="controller.activate(pane.id, $event)" @open="openMenu($event, pane.id)" @menu="operations($event, pane.id)" @close-pane="controller.closePane(pane.id)" @split-pull="beginSplitPull($event, pane.id, 'top-left')" @close="controller.closeTab(pane.id, $event)" @tab-menu="(event, tab) => tabMenu(event, pane.id, tab)" @drag="(event, tab) => dragStart(event, pane.id, tab)" />
      <div v-if="!pane.tabs.length" class="split-empty"><span>{{ t('留一个空间，打开需要的内容') }}</span><button class="split-text-button" type="button" @click="openMenu($event, pane.id)">{{ t('打开内容') }}</button><small>{{ t('也可以将标签拖到这里') }}</small></div>
    </section>
    <!-- Flat, identity-keyed content keeps editors and webviews mounted while their tabs move. -->
    <section v-for="{ pane, tab } in allTabs" :id="`split-content-${tab.id}`" :key="tab.id" v-show="tabVisible(pane, tab)" :class="['split-tab-content', `split-tab-content--${tab.kind}`]" :style="css(activeRect(pane), true)" :data-selection-document="`split:${tab.id}`" :data-source-session-id="tab.kind === 'agent' ? tab.sessionId : undefined" role="tabpanel" :aria-labelledby="`split-tab-${tab.id}`" :tabindex="0" @pointerdown="controller.activate(pane)" @focusin="controller.activate(pane)" @keydown.esc.stop @dragover="dragOver($event, pane)">
      <slot :tab="tab" :pane="pane" :visible="tabVisible(pane, tab)" />
    </section>
    <!-- user:“像 Blender 一样从分屏的角进行拖拽...偏靠角的那一块应该留给创建分屏的判定”+(左上/左下可见角柄；右下短动作区；右上留给加号与关闭)。 -->
    <template v-for="pane in state.panes" :key="`corner-${pane.id}`">
      <div v-show="paneVisible(pane.id)" class="split-corner-grip split-corner-grip--bottom-left" :style="cornerStyle(pane.id, 'bottom-left')" :title="t('拖动角新建分屏')" aria-hidden="true" @pointerdown.prevent="beginSplitPull($event, pane.id, 'bottom-left')"></div>
      <div v-show="paneVisible(pane.id)" class="split-corner-grip split-corner-grip--bottom-right split-corner-grip--ghost" :style="cornerStyle(pane.id, 'bottom-right')" :title="t('拖动角新建分屏')" aria-hidden="true" @pointerdown.prevent="beginSplitPull($event, pane.id, 'bottom-right')"></div>
    </template>
    <template v-if="!focused">
      <div v-for="divider in normal.dividers" :key="divider.id" class="split-divider" :class="[`split-divider--${divider.direction}`, { 'is-resizing': resizing === divider.id }]" :style="dividerStyle(divider)" role="separator" tabindex="0" :aria-label="t('调整分屏大小')" :title="t('拖动中段调整 · Ctrl 吸附 · 双击均分 · 右键合并/交换 · Esc 撤回')" :aria-orientation="divider.direction === 'columns' ? 'vertical' : 'horizontal'" :aria-valuemin="0" :aria-valuemax="100" :aria-valuenow="Math.round(divider.ratio * 100)" @pointerdown="resize($event, divider)" @keydown="keyResize($event, divider)" @contextmenu.prevent.stop="dividerMenu($event, divider)" @dblclick="resizeSplit(state.tree, divider.id, .5, divider.direction === 'columns' ? divider.parent.width : divider.parent.height)"></div>
    </template>
    <div v-if="focused && !state.hidden && Object.keys(state.panes).length" class="split-focus-switch"><button class="split-text-button" type="button" @click="switchScreen">{{ t('查看其他屏') }} · {{ Object.keys(state.panes).length + 1 }}</button><button v-if="state.focused" class="split-icon-button" type="button" :aria-label="t('退出聚焦')" @click="state.focused = null"><PanelTopClose :size="14" /></button></div>
    <Transition name="split-drop">
      <div v-if="preview" class="split-split-preview" :class="`split-split-preview--${preview.mode}`">
        <div v-for="(rect, index) in preview.areas" :key="index" class="split-split-preview-area" :style="css(rect)"></div>
        <div v-if="preview.line" class="split-split-preview-line" :style="css(preview.line)"></div>
      </div>
    </Transition>
  </div>
</template>
