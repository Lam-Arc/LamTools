<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, BookOpen, FileText, FolderTree, Globe, PanelLeftClose, PanelTopClose, Columns2, Rows2, Maximize2, X, LayoutGrid } from 'lucide-vue-next'
import CoreSplitPane from './CoreSplitPane.vue'
import { openContextMenu } from './context-menu/context-menu'
import type { ContextMenuEntry } from './context-menu/types'
import { layoutRects, minimumSize, moveTab, resizeSplit, SPLIT_TAB_BAR_HEIGHT, type Divider, type Rect, type SplitContent, type SplitEdge, type SplitTab } from '@/split/layout'
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
  const add = (kind: 'page' | 'browser' | 'editor' | 'files', resource: string, title: string) => () => { props.controller.add(kind, resource, title, pane) }
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
    { label: t('文件树'), icon: FolderTree, action: create('files', props.workRoot, t('文件')) },
  ]
}
// user:“在分屏内选择分屏类型和标签页”+(手柄点开先选方向，再选新分屏要承载的标签内容)。
function openSplitMenu(event: MouseEvent, pane: string) {
  const directions: { edge: SplitEdge; label: string; icon: typeof ArrowRight }[] = [
    { edge: 'right', label: t('向右分屏'), icon: ArrowRight },
    { edge: 'bottom', label: t('向下分屏'), icon: ArrowDown },
    { edge: 'left', label: t('向左分屏'), icon: ArrowLeft },
    { edge: 'top', label: t('向上分屏'), icon: ArrowUp },
  ]
  openContextMenu({ event, ariaLabel: t('新建分屏'), items: directions.map(({ edge, label, icon }) => ({
    type: 'submenu' as const, label, icon, disabled: !canSplit(pane, edge), children: splitContentItems(pane, edge),
  })) })
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
const dropStyle = computed(() => {
  if (!drop.value) return {}
  const rect = { ...activeRect(drop.value.pane) }, edge = drop.value.edge
  if (edge === 'left' || edge === 'right') { rect.width /= 2; if (edge === 'right') rect.x += rect.width }
  if (edge === 'top' || edge === 'bottom') { rect.height /= 2; if (edge === 'bottom') rect.y += rect.height }
  return css(rect)
})
const dropLabel = computed(() => drop.value?.edge === 'center' ? t('合并标签') : ({ left: t('向左分屏'), right: t('向右分屏'), top: t('向上分屏'), bottom: t('向下分屏') })[drop.value?.edge || 'right'])
// user:“拉起其他分屏的时候...通过拖动拉起，而不是点击按钮。就类似 blender”+(手柄拖动时按方向拉出预览，松手直接在指针处落下一块新屏)。
const pull = ref<{ pane: string; edge: SplitEdge; rect: Rect; ratio: number } | null>(null)
let stopPull: (() => void) | undefined
const pullLabel = computed(() => ({ left: t('向左分屏'), right: t('向右分屏'), top: t('向上分屏'), bottom: t('向下分屏') })[pull.value?.edge || 'right'])
function clampSplitShare(pane: string, edge: SplitEdge, share: number, extent: number) {
  const key = edge === 'left' || edge === 'right' ? 'width' : 'height'
  const existing = minimumSize({ type: 'pane', id: pane })[key], created = minimumSize({ type: 'pane', id: '__new-split' })[key]
  const lo = created / extent, hi = 1 - existing / extent
  return lo <= hi ? Math.max(lo, Math.min(hi, share)) : .5
}
function beginSplitPull(event: PointerEvent, pane: string) {
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
    pull.value = null; stopPull = undefined
  }
  const move = (e: PointerEvent) => {
    const dx = e.clientX - startX, dy = e.clientY - startY
    if (!moved && Math.hypot(dx, dy) < 6) return
    moved = true
    const columns = Math.abs(dx) >= Math.abs(dy)
    const edge: SplitEdge = columns ? (dx >= 0 ? 'right' : 'left') : (dy >= 0 ? 'bottom' : 'top')
    if (!canSplit(pane, edge)) { pull.value = null; document.body.classList.remove('split-is-pulling'); return }
    const extent = Math.max(1, columns ? source.width : source.height)
    const share = clampSplitShare(pane, edge, .5 + Math.abs(columns ? dx : dy) / extent * .5, extent)
    const size = Math.round(extent * share)
    const ratio = edge === 'left' || edge === 'top' ? share : 1 - share
    const rect = edge === 'right' ? { x: source.x + source.width - size, y: source.y, width: size, height: source.height }
      : edge === 'left' ? { x: source.x, y: source.y, width: size, height: source.height }
      : edge === 'bottom' ? { x: source.x, y: source.y + source.height - size, width: source.width, height: size }
      : { x: source.x, y: source.y, width: source.width, height: size }
    pull.value = { pane, edge, rect, ratio }
    document.body.classList.add('split-is-pulling')
  }
  const finish = (e: PointerEvent) => {
    const dropped = pull.value, dragged = moved
    stop()
    if (!dragged) { openSplitMenu(e, pane); return }
    if (dropped) props.controller.splitAt(dropped.pane, dropped.edge, dropped.ratio)
  }
  const cancel = () => stop()
  const cancelKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); stop() } }
  stopPull = stop
  try { handle.setPointerCapture?.(event.pointerId) } catch { /* Synthetic or already-released pointers still drag via window listeners. */ }
  handle.addEventListener('lostpointercapture', cancel)
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', finish)
  window.addEventListener('pointercancel', cancel); window.addEventListener('keydown', cancelKey)
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
  const move = (e: PointerEvent) => { const box = root.value!.getBoundingClientRect(), columns = divider.direction === 'columns'; resizeSplit(state.tree, divider.id, ((columns ? e.clientX - box.left - divider.parent.x : e.clientY - box.top - divider.parent.y)) / ((columns ? divider.parent.width : divider.parent.height) - 2), columns ? divider.parent.width : divider.parent.height) }
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
defineExpose({ operations, openMenu, openSplitMenu, measure })
</script>
<template>
  <div ref="root" class="split-workspace" :class="{ 'split-workspace--open': Object.keys(state.panes).length > 0 }" :style="{ '--split-tabbar-height': `${SPLIT_TAB_BAR_HEIGHT}px` }" data-region="split" @drop="onDrop">
    <div v-if="drag" class="split-main-drop" :style="css(activeRect('main'))" @dragover="dragOver($event, 'main')"></div>
    <section v-for="pane in state.panes" :key="pane.id" v-show="paneVisible(pane.id)" class="split-pane-frame" :class="{ 'is-entering': entering.has(pane.id), 'is-pulling': pull?.pane === pane.id }" :style="css(activeRect(pane.id))" :aria-label="t('分屏')" @pointerdown="controller.activate(pane.id)" @dragover="dragOver($event, pane.id)">
      <CoreSplitPane :pane="pane" :active="state.activePane === pane.id" :dirty="dirty" @focus="controller.activate(pane.id)" @activate="controller.activate(pane.id, $event)" @open="openMenu($event, pane.id)" @menu="operations($event, pane.id)" @split="openSplitMenu($event, pane.id)" @split-pull="beginSplitPull($event, pane.id)" @close="controller.closeTab(pane.id, $event)" @tab-menu="(event, tab) => tabMenu(event, pane.id, tab)" @drag="(event, tab) => dragStart(event, pane.id, tab)" />
      <div v-if="!pane.tabs.length" class="split-empty"><span>{{ t('留一个空间，打开需要的内容') }}</span><button class="split-text-button" type="button" @click="openMenu($event, pane.id)">{{ t('打开内容') }}</button><small>{{ t('也可以将标签拖到这里') }}</small></div>
    </section>
    <!-- Flat, identity-keyed content keeps editors and webviews mounted while their tabs move. -->
    <section v-for="{ pane, tab } in allTabs" :id="`split-content-${tab.id}`" :key="tab.id" v-show="tabVisible(pane, tab)" :class="['split-tab-content', `split-tab-content--${tab.kind}`]" :style="css(activeRect(pane), true)" :data-selection-document="`split:${tab.id}`" :data-source-session-id="tab.kind === 'agent' ? tab.sessionId : undefined" role="tabpanel" :aria-labelledby="`split-tab-${tab.id}`" :tabindex="0" @pointerdown="controller.activate(pane)" @focusin="controller.activate(pane)" @keydown.esc.stop @dragover="dragOver($event, pane)">
      <slot :tab="tab" :pane="pane" :visible="tabVisible(pane, tab)" />
    </section>
    <template v-if="!focused">
      <div v-for="divider in normal.dividers" :key="divider.id" class="split-divider" :class="[`split-divider--${divider.direction}`, { 'is-resizing': resizing === divider.id }]" :style="css(divider.rect)" role="separator" tabindex="0" :aria-label="t('调整分屏大小')" :title="t('拖动调整 · 双击均分 · Esc 撤回')" :aria-orientation="divider.direction === 'columns' ? 'vertical' : 'horizontal'" :aria-valuemin="0" :aria-valuemax="100" :aria-valuenow="Math.round(divider.ratio * 100)" @pointerdown="resize($event, divider)" @keydown="keyResize($event, divider)" @dblclick="resizeSplit(state.tree, divider.id, .5, divider.direction === 'columns' ? divider.parent.width : divider.parent.height)"></div>
    </template>
    <div v-if="focused && !state.hidden && Object.keys(state.panes).length" class="split-focus-switch"><button class="split-text-button" type="button" @click="switchScreen">{{ t('查看其他屏') }} · {{ Object.keys(state.panes).length + 1 }}</button><button v-if="state.focused" class="split-icon-button" type="button" :aria-label="t('退出聚焦')" @click="state.focused = null"><PanelTopClose :size="14" /></button></div>
    <Transition name="split-drop"><div v-if="drop" class="split-drop-preview" :style="dropStyle">{{ dropLabel }}</div></Transition>
    <Transition name="split-drop"><div v-if="pull" class="split-drop-preview split-pull-preview" :style="css(pull.rect)">{{ pullLabel }}</div></Transition>
  </div>
</template>
