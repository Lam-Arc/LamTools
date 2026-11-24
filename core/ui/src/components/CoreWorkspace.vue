<script lang="ts">
/**
 * 标签拖拽的纯逻辑（供组件与单测共用）。
 *
 * user:“落点判定只用 workspace/hit.ts：hitWorkspace(…) 与 dropEdgeFor(…)；不要自己写第二套几何”+
 * (所以这里只做“把命中结果翻译成计划”，一个像素都不自己算：矩形、边缘带、标签栏带全部来自引擎)。
 */
import {
  areasOf,
  dropEdgeFor,
  hitWorkspace,
  type Rect,
  type WorkspaceGeometry,
  type WorkspaceModel,
} from '@/workspace'

/** user:“拖动距离 <4px 视为点击”+(阈值是唯一口径，组件与测试都读它)。 */
// user:“拖动标签太敏感了，现在稍微一拖就分屏了”+(提高拖拽起步阈值到 12px，避免点击标签时轻微抖动就触发分屏/拖出)。
export const TAB_DRAG_THRESHOLD = 12

/** 分隔条两侧各自至少要留下的像素：拖动只缩放，绝不把任何一侧压没。 */
export const DIVIDER_MIN_PANE_PX = 96

/**
 * user:“分屏有问题，我随便拖动了一下导致分屏完全消失，无法出现了”+
 * (分隔条只负责缩放：比例被夹在“两侧都还留得住 DIVIDER_MIN_PANE_PX”的范围内，
 *  拖动永远不会折叠或剪掉分屏——收起分屏只留给显式的「暂存收起分屏」)。
 */
export function clampDividerRatio(raw: number, extent: number): number {
  const value = Number.isFinite(raw) ? Math.min(1, Math.max(0, raw)) : .5
  if (!(extent > 0)) return value
  const min = Math.min(.4, Math.max(.02, DIVIDER_MIN_PANE_PX / extent))
  return Math.min(1 - min, Math.max(min, value))
}

export interface DragPoint { x: number; y: number }
export interface TabDragSource { pane: string; index: number; surfaceId: string }

/** 一次落点的结论：排序 / 跨区移动 / 切分 / 浮层 / 无操作。 */
export type TabDropPlan =
  | { kind: 'reorder'; pane: string; from: number; to: number }
  | { kind: 'move'; from: { pane: string; index: number }; to: { pane: string; index: number } }
  | { kind: 'split'; pane: string; edge: 'left' | 'right' | 'top' | 'bottom'; from: { pane: string; index: number } }
  | { kind: 'float'; surfaceId: string; point: DragPoint }
  | { kind: 'none' }

/**
 * user:“三种结果：同区排序、跨区移动、拖到区域边缘=切分；拖到内容区=移动；拖到标签栏=移动（不是切分）”+
 * user:“同时让每个标签都可被拖拽到区域成为浮层”+
 * (拖到标签栏=同区排序/跨区移动；拖到边缘=切分；拖到内容区或空白处=脱离成为浮层)。
 */
export function planTabDrop(input: {
  geometry: WorkspaceGeometry
  model: WorkspaceModel
  point: DragPoint
  source: TabDragSource
  band?: number
}): TabDropPlan {
  const { geometry, model, point, source } = input
  // user:“其实主要是页眉和页眉以上不应该作为可生效区域”+(拖到工作区页眉以上/标题栏时不触发浮窗或分屏)
  if (point.y < 0) return { kind: 'none' }
  const hit = hitWorkspace(geometry, model, point, { priority: 'tabbar-first', edgeBand: 24 })
  if (hit.kind === 'none') {
    return source.surfaceId !== 'agent-main' ? { kind: 'float', surfaceId: source.surfaceId, point } : { kind: 'none' }
  }
  if (hit.kind !== 'tabbar' && hit.kind !== 'content' && hit.kind !== 'edge') return { kind: 'none' }
  const area = areasOf(model).find(item => item.id === hit.areaId)
  const areaGeo = geometry.areas[hit.areaId]
  const rect = areaGeo?.rect
  if (!area || !rect) return { kind: 'none' }

  if (hit.kind === 'edge') {
    // 单标签区域不允许拖到自身边缘拆出一个空区域。
    if (hit.areaId === source.pane && area.tabs.length <= 1) return { kind: 'none' }
    const edge = dropEdgeFor(point, rect, input.band ?? .12)
    // 页眉高度范围内的上边缘不触发 top 分屏，避免在标签栏/页眉横向拖动时误分屏。
    const headerBottom = Math.max(rect.y + 36, areaGeo?.contentRect.y ?? rect.y + 36)
    if (edge === 'top' && point.y <= headerBottom) return { kind: 'none' }
    if (edge !== 'center') {
      return { kind: 'split', pane: hit.areaId, edge, from: { pane: source.pane, index: source.index } }
    }
  }

  if (hit.kind === 'content' && source.surfaceId !== 'agent-main') {
    return { kind: 'float', surfaceId: source.surfaceId, point }
  }

  // 拖到标签栏：同区排序、跨区移动。
  const to = { pane: hit.areaId, index: area.tabs.length }
  if (hit.areaId === source.pane) return { kind: 'reorder', pane: hit.areaId, from: source.index, to: area.tabs.length }
  return { kind: 'move', from: { pane: source.pane, index: source.index }, to }
}

/** 拖动中的预览：显示清晰的目标骨架虚影（切分显示半区虚影，移动/排序显示目标区，浮层显示浮窗轮廓）。 */
export function dropPreview(plan: TabDropPlan, geometry: WorkspaceGeometry): Rect | null {
  if (plan.kind === 'float') {
    return {
      x: Math.max(0, Math.round(plan.point.x - 220)),
      y: Math.max(0, Math.round(plan.point.y - 18)),
      width: 460,
      height: 360,
    }
  }
  if (plan.kind === 'split') {
    const rect = geometry.areas[plan.pane]?.rect
    if (!rect) return null
    const halfW = Math.round(rect.width / 2)
    const halfH = Math.round(rect.height / 2)
    if (plan.edge === 'left') return { x: rect.x, y: rect.y, width: halfW, height: rect.height }
    if (plan.edge === 'right') return { x: rect.x + halfW, y: rect.y, width: rect.width - halfW, height: rect.height }
    if (plan.edge === 'top') return { x: rect.x, y: rect.y, width: rect.width, height: halfH }
    return { x: rect.x, y: rect.y + halfH, width: rect.width, height: rect.height - halfH }
  }
  if (plan.kind === 'move' || plan.kind === 'reorder') {
    const pane = plan.kind === 'move' ? plan.to.pane : plan.pane
    const rect = geometry.areas[pane]?.rect
    if (!rect) return null
    return { x: rect.x, y: rect.y, width: rect.width, height: Math.min(36, rect.height) }
  }
  return null
}

export type TabDragPhase = 'idle' | 'pending' | 'dragging'

export interface TabDragMachine {
  readonly phase: TabDragPhase
  readonly source: TabDragSource | null
  down: (source: TabDragSource, point: DragPoint) => void
  move: (point: DragPoint) => TabDragPhase
  up: (commit?: () => void) => void
  cancel: () => void
}

/**
 * user:“idle → pending(4px) → dragging → commit/cancel”+
 * user:“拖动开始时 controller.beginInteraction('draggingTab')，提交走 switchTabInteraction(commit)
 * （若控制器没有该方法，就用 beginInteraction + endInteraction(commit)）”+
 * (控制器没有 switchTabInteraction，所以提交走 `endInteraction(commit)`：先执行变更、再回 idle，
 *  网页因此只在手势期间让位，松手立刻恢复——这正是它该有的时序)。
 */
export function createTabDragMachine(options: {
  begin: () => void
  end: (commit?: () => void) => void
  threshold?: number
}): TabDragMachine {
  const threshold = Math.max(0, options.threshold ?? TAB_DRAG_THRESHOLD)
  let phase: TabDragPhase = 'idle'
  let source: TabDragSource | null = null
  let origin: DragPoint = { x: 0, y: 0 }
  let began = false

  return {
    get phase() { return phase },
    get source() { return source },
    down(next, point) {
      phase = 'pending'
      source = next
      origin = { x: point.x, y: point.y }
      began = false
    },
    move(point) {
      if (phase !== 'pending') return phase
      if (Math.hypot(point.x - origin.x, point.y - origin.y) < threshold) return phase
      phase = 'dragging'
      if (!began) { began = true; options.begin() }
      return phase
    },
    up(commit) {
      if (began) options.end(commit)
      else if (commit) commit()
      phase = 'idle'
      source = null
      began = false
    },
    cancel() {
      if (began) options.end(undefined)
      phase = 'idle'
      source = null
      began = false
    },
  }
}
</script>

<script setup lang="ts">
/**
 * 工作区外壳（V2-C1b-4）：区域、分隔条、浮层、折叠提示、标签拖拽、键盘。
 *
 * user:“用新引擎把工作区外壳换掉…slot 契约保持 { tab, pane, visible }，这样里面的
 * CoreSplitContent 一行不用改”+
 * (外壳只做“照几何摆东西”：矩形全部来自 `controller.geometry`（computeWorkspace），
 *  组件自己不量内容宿主——那是旧版“网页跑到别处”的来源。
 *
 * user:“删掉分屏空间不足的提示”+(几何缩小时继续使用紧凑布局，失败提示由操作本身触发)。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, shallowReactive, watch } from 'vue'
import { keyboardIntent, type WorkspaceController } from '@/workspace/useWorkspace'
import { computeYieldInsets, snapRatio } from '@/workspace'
import type { SplitTab } from '@/workspace/types'
import CoreWorkspaceArea from './CoreWorkspaceArea.vue'
import CoreWorkspaceFloat from './CoreWorkspaceFloat.vue'
import CoreWorkspaceContentHost from './CoreWorkspaceContentHost.vue'
import { WORKSPACE_COMPOSED_RECT, type WorkspaceContentTarget } from './workspaceInjection'
// user:“中间消失了”+(裁切由独立模块提供，打包时可完整挂载工作区)。
import { buildCutoutClipPath, workspaceFloatCutouts } from '@/workspace/composition'

import '@/styles/workspace-v2.css'

const props = defineProps<{ controller: WorkspaceController; workRoot: string; dirty?: Set<string> }>()
const emit = defineEmits<{ geometry: [style: Record<string, string>]; visibility: [id: string, visible: boolean] }>()

const root = ref<HTMLElement | null>(null)
const rootOrigin = ref({ x: 0, y: 0 })
const windowWidth = ref(0)
const controller = props.controller

// ---------------------------------------------------------------------------
// 外壳矩形：只报一次自己的尺寸，之后所有几何都由引擎算。
// ---------------------------------------------------------------------------
let observer: ResizeObserver | null = null
let frame = 0

function measure() {
  frame = 0
  const rect = root.value?.getBoundingClientRect()
  if (!rect || rect.width <= 0) return
  windowWidth.value = window.innerWidth
  // user:“网页遇见分屏会出现细线”+(网页以物理像素对齐，工作区原点保留小数，避免把裁切边界错移半个 CSS 像素)。
  rootOrigin.value = { x: rect.left, y: rect.top }
  controller.setBounds({ x: 0, y: 0, width: Math.round(rect.width), height: Math.round(rect.height) })
}

function schedule() {
  if (frame) return
  frame = typeof requestAnimationFrame === 'function' ? requestAnimationFrame(measure) : (measure(), 0)
}

const geometry = computed(() => controller.geometry.value)
const areas = computed(() => controller.areas.value)
// user:“快速精准高效的解决”+(内容按标签挂载一次，分屏、浮层和收起只变更位置与显隐)。
const targets = shallowReactive(new Map<string, WorkspaceContentTarget>())
function setTarget(key: string, target: WorkspaceContentTarget | null) {
  if (target && targets.get(key)?.element !== target.element) targets.set(key, target)
  if (!target) targets.delete(key)
}
const placedContent = computed(() => {
  const visible = !controller.state.hidden
  const placed = controller.tabs.value.map(({ tab, pane }) => {
    const floating = pane === 'float'
    return {
      tab,
      pane,
      host: targets.get(floating ? `float:${tab.id}` : `area:${pane}`),
      visible: visible && (floating || (controller.areaVisible(pane) && controller.state.panes[pane]?.activeTab === tab.id)),
    }
  })
  for (const tab of controller.parkedFloats.value) {
    if (!placed.some(entry => entry.tab.id === tab.id)) placed.push({ tab, pane: 'parked', host: undefined, visible: false })
  }
  return placed
})

// user:“层级应为红>绿>黄”+(网页用实际显示范围，让比它低的表面挖洞，比它高的浮窗照常遮挡)。
const liveComposedRects = shallowReactive(new Map<string, Rect>())
provide(WORKSPACE_COMPOSED_RECT, (id, rect) => {
  if (!rect) {
    liveComposedRects.delete(id)
    return
  }
  const previous = liveComposedRects.get(id)
  if (previous && previous.x === rect.x && previous.y === rect.y
    && previous.width === rect.width && previous.height === rect.height) return
  liveComposedRects.set(id, rect)
})
const localComposedRects = computed(() => new Map(Array.from(liveComposedRects,
  ([id, rect]) => [id, { ...rect, x: rect.x - rootOrigin.value.x, y: rect.y - rootOrigin.value.y }],
)))
const floatCutouts = computed(() => {
  const order = controller.floatOrder.value
  return new Map(order.map(id => [id, workspaceFloatCutouts(order, localComposedRects.value, id)]))
})
const liveComposedFloatHoles = computed(() => workspaceFloatCutouts(controller.floatOrder.value, localComposedRects.value))

/**
 * user:“存在分屏时将窗口变为小窗口…”+ 主区矩形翻成旧变量名（`--split-primary-*`），App 那两行不用改。
 */
function onCloseTab(entry: (typeof areas.value)[number], surfaceId: string) {
  const tab = entry.tabs.find(item => item.id === surfaceId)
  if (!tab) return
  const isLastMainBrowser = entry.area.role === 'main'
    && tab.kind === 'browser'
    && entry.tabs.filter(item => item.kind === 'browser').length <= 1
  // user:“分屏最后一个标签关掉后为什么分屏不消失”+
  // (主区浏览器关闭最后一个网页标签时保留空白新标签；辅助分屏关闭最后一个标签时直接由引擎收拢销毁该分屏)。
  controller.closeTab(entry.area.id, tab, () => {
    if (isLastMainBrowser) controller.add('browser', '', '新标签', entry.area.id)
  })
}

function emitShellStyle() {
  const main = areas.value.find(entry => entry.area.role === 'main') ?? areas.value[0]
  const rect = main?.geometry?.rect
  if (!rect) return
  // user:“收起分屏时主内容会填充吗”+(收起分屏时主内容必须铺满整个工作区，不能停留在收起前的分屏宽度)
  if (controller.state.hidden) {
    const fullWidth = Math.max(rect.width, ...areas.value.map(entry => (entry.geometry?.rect.x ?? 0) + (entry.geometry?.rect.width ?? 0)))
    const fullHeight = Math.max(rect.height, ...areas.value.map(entry => (entry.geometry?.rect.y ?? 0) + (entry.geometry?.rect.height ?? 0)))
    emit('geometry', {
      '--split-primary-x': '0px',
      '--split-primary-y': '0px',
      '--split-primary-width': `${fullWidth}px`,
      '--split-primary-height': `${fullHeight}px`,
      '--split-primary-bottom': '0px',
      '--split-primary-visible': fullWidth ? 'visible' : 'hidden',
      '--ws2-yield-left': '0px',
      '--ws2-yield-right': '0px',
      '--ws2-yield-top': '0px',
      '--ws2-yield-bottom': '0px',
    })
    return
  }
  // user:“依旧不可见，你来完成新布局系统的开发工作”+(同步输出自由让位内边距 CSS 变量，使开启让位的浮窗自动缩让主区内容并保留最小可用空间)
  const yieldInsets = computeYieldInsets(
    rect,
    controller.floats.value.filter(f => f.yieldEnabled).map(f => f.rect),
  )
  emit('geometry', {
    '--split-primary-x': `${rect.x}px`,
    '--split-primary-y': `${rect.y}px`,
    '--split-primary-width': `${rect.width}px`,
    '--split-primary-height': `${rect.height}px`,
    // user:“分屏布局下，消息流尾部区域会低于输入框上沿，导致尾部消息被遮挡”+(上下分屏时输入框也停在主区下沿)。
    '--split-primary-bottom': `${Math.max(0, controller.bounds.value.height - rect.y - rect.height)}px`,
    '--split-primary-visible': rect.width ? 'visible' : 'hidden',
    '--ws2-yield-left': `${yieldInsets.left}px`,
    '--ws2-yield-right': `${yieldInsets.right}px`,
    '--ws2-yield-top': `${yieldInsets.top}px`,
    '--ws2-yield-bottom': `${yieldInsets.bottom}px`,
    '--ws2-main-cutout': buildCutoutClipPath(rect, liveComposedFloatHoles.value) ?? 'none',
  })
}

// ---------------------------------------------------------------------------
// 分隔条
// ---------------------------------------------------------------------------
function leavesOf(node: WorkspaceController['model']['value']['tree']): string[] {
  if (node.kind === 'leaf') return [node.area.id]
  return [...leavesOf(node.a), ...leavesOf(node.b)]
}

interface DividerView { path: number[]; direction: 'row' | 'column'; union: Rect; strip: Rect; boundary: { x: number; y: number }; leftLeaves: string[]; rightLeaves: string[] }

const dividers = computed<DividerView[]>(() => {
  const list: DividerView[] = []
  const rectOf = (ids: string[]): Rect | null => {
    const rects = ids.map(id => geometry.value.areas[id]?.rect).filter((rect): rect is Rect => Boolean(rect))
    if (!rects.length) return null
    const x = Math.min(...rects.map(rect => rect.x))
    const y = Math.min(...rects.map(rect => rect.y))
    const right = Math.max(...rects.map(rect => rect.x + rect.width))
    const bottom = Math.max(...rects.map(rect => rect.y + rect.height))
    return { x, y, width: right - x, height: bottom - y }
  }
  const walk = (node: WorkspaceController['model']['value']['tree'], path: number[]) => {
    if (node.kind === 'leaf') return
    const leftLeaves = leavesOf(node.a)
    const rightLeaves = leavesOf(node.b)
    const a = rectOf(leftLeaves)
    const b = rectOf(rightLeaves)
    if (a && b) {
      const union: Rect = node.direction === 'row'
        ? { x: a.x, y: Math.min(a.y, b.y), width: (b.x + b.width) - a.x, height: Math.max(a.height, b.height) }
        : { x: Math.min(a.x, b.x), y: a.y, width: Math.max(a.width, b.width), height: (b.y + b.height) - a.y }
      const strip: Rect = node.direction === 'row'
        ? { x: a.x + a.width - 6, y: union.y, width: 12, height: union.height }
        : { x: union.x, y: a.y + a.height - 6, width: union.width, height: 12 }
      // 分隔条的边界 = 左/上子树的右下沿（行分割取右沿，列分割取下沿）。
      const boundary = node.direction === 'row'
        ? { x: a.x + a.width, y: union.y }
        : { x: union.x, y: a.y + a.height }
      list.push({ path, direction: node.direction, union, strip, boundary, leftLeaves, rightLeaves })
    }
    walk(node.a, [...path, 0])
    walk(node.b, [...path, 1])
  }
  walk(controller.model.value.tree, [])
  return list
})

/**
 * user:“无法拖动，它位置只会大幅跳变”+
 * (分隔条的落点必须是“按下时的边界 + 指针位移”：之前拿指针的屏幕坐标直接对工作区本地坐标算比例，
 *  被左侧栏/标题栏的偏移量污染，第一下就跳到被夹死的极端，于是只能跳、拖不动)。
 */
let drag: { view: DividerView; start: number; extent: number; origin: number; boundary: number } | null = null

// user:“分屏拖动手感不佳，卡顿/不跟手”+
// (每个 pointermove 都 clone 一次模型会在一帧里重复提交；这里同帧只落一次，松手补最后一帧。
//  吸附也从 4% 的比率带改成 8px 的像素带：只有真的靠近 25/50/75 才吸，其他位置完全跟手)。
let dividerFrame = 0
let pendingDivider: { path: number[]; ratio: number } | null = null
function applyPendingDivider() {
  const next = pendingDivider
  pendingDivider = null
  if (next) controller.resizeDivider(next.path, next.ratio)
}
function scheduleDivider(path: number[], ratio: number) {
  pendingDivider = { path: [...path], ratio }
  if (dividerFrame) return
  dividerFrame = requestAnimationFrame(() => { dividerFrame = 0; applyPendingDivider() })
}
function flushDivider() {
  if (dividerFrame) { cancelAnimationFrame(dividerFrame); dividerFrame = 0 }
  applyPendingDivider()
}
function cancelDivider() {
  if (dividerFrame) { cancelAnimationFrame(dividerFrame); dividerFrame = 0 }
  pendingDivider = null
}

function onDividerDown(view: DividerView, event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  cancelDivider()
  const horizontal = view.direction === 'row'
  drag = {
    view,
    start: horizontal ? event.clientX : event.clientY,
    extent: horizontal ? view.union.width : view.union.height,
    origin: horizontal ? view.union.x : view.union.y,
    boundary: horizontal ? view.boundary.x : view.boundary.y,
  }
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  controller.beginInteraction('resizingDivider')
}

function onDividerMove(event: PointerEvent) {
  if (!drag) return
  const horizontal = drag.view.direction === 'row'
  const current = horizontal ? event.clientX : event.clientY
  // 只认位移：边界（本地坐标）+ 指针位移（屏幕坐标之差，与偏移量无关）。
  const raw = drag.extent > 0 ? (drag.boundary + (current - drag.start) - drag.origin) / drag.extent : .5
  // user:“分屏有问题，我随便拖动了一下导致分屏完全消失，无法出现了”+
  // (拖分隔条只改比例，绝不折叠/销毁分屏：越界一律夹到“两侧都还留得住”的最小比例，
  //  收起分屏只留给显式的「暂存收起分屏」——拖动永远拖不没东西)。
  const tolerance = drag.extent > 0 ? 8 / drag.extent : .02
  const snapped = snapRatio(clampDividerRatio(raw, drag.extent), { snap: !event.altKey, tolerance })
  scheduleDivider(drag.view.path, clampDividerRatio(snapped, drag.extent))
}

function onDividerUp() {
  if (!drag) return
  flushDivider()
  drag = null
  controller.endInteraction()
}

function onDividerDouble(view: DividerView) {
  controller.resizeDivider(view.path, .5)
}

// ---------------------------------------------------------------------------
// 标签拖拽：状态机 + 引擎落点
// ---------------------------------------------------------------------------
const dragMachine = createTabDragMachine({
  // user:“拖动期间网页让位：用控制器 interactionPhase 驱动，不新增第二套布尔”
  begin: () => controller.beginInteraction('draggingTab'),
  end: commit => controller.endInteraction(commit),
})

const dragPlan = ref<TabDropPlan | null>(null)
/** 响应式镜像：状态机是纯对象，模板要跟着变就得有一份 ref。 */
const dragPhase = ref<TabDragPhase>('idle')

function localPoint(event: PointerEvent): DragPoint {
  const rect = root.value?.getBoundingClientRect()
  return rect
    ? { x: event.clientX - rect.left, y: event.clientY - rect.top }
    : { x: event.clientX, y: event.clientY }
}

function onPinHover(surfaceId: string, active: boolean) {
  if (!active) {
    if (controller.pinPreview.value?.surfaceId === surfaceId) controller.pinPreview.value = null
    return
  }
  if (controller.bounds.value.width <= 0) measure()
  const plan = controller.pinPlan(surfaceId)
  controller.pinPreview.value = plan.ok && plan.rect
    ? { surfaceId, rect: plan.rect, areaId: plan.areaId ?? 'aux' }
    : null
}

// user:“点固定没反应，check”+(固定前确保视口已测量；若极端窄窗下仍无法分屏，给出空间不足提示而非静默无响应)。
function onPinCommit(surfaceId: string) {
  onPinHover(surfaceId, false)
  if (controller.bounds.value.width <= 0) measure()
  controller.pinCommit(surfaceId)
}

function applyPlan(plan: TabDropPlan) {
  if (plan.kind === 'reorder') { controller.reorderTab(plan.pane, plan.from, plan.to); return }
  if (plan.kind === 'move') { controller.moveTab(plan.from, plan.to); return }
  if (plan.kind === 'float') {
    const res = controller.setSurfaceMode(plan.surfaceId, 'float')
    if (!res.ok) return
    const floated = controller.floats.value.find(f => f.tab.id === plan.surfaceId)
    if (floated) {
      controller.moveFloat(plan.surfaceId, {
        x: Math.max(0, Math.round(plan.point.x - floated.rect.width * 0.45)),
        y: Math.max(0, Math.round(plan.point.y - 18)),
        width: floated.rect.width,
        height: floated.rect.height,
      })
    }
    return
  }
  if (plan.kind === 'split') {
    const created = controller.split(plan.pane, plan.edge)
    if (!created) return
    // 被拖的标签跟着新区域走；moveTab 会把源区域那份摘掉，所以不会有残留。
    controller.moveTab(plan.from, { pane: created, index: 0 })
  }
}

function onTabPointerDown(pane: string, surfaceId: string, event: PointerEvent) {
  if (event.button !== 0) return
  const area = areas.value.find(entry => entry.area.id === pane)
  const index = area ? area.tabs.findIndex(tab => tab.id === surfaceId) : -1
  if (index < 0) return
  dragPlan.value = null
  dragMachine.down({ pane, index, surfaceId }, localPoint(event))
  dragPhase.value = 'pending'
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragUp)
  window.addEventListener('pointercancel', onDragCancel)
}

function onDragMove(event: PointerEvent) {
  const point = localPoint(event)
  const phase = dragMachine.move(point)
  dragPhase.value = phase
  const source = dragMachine.source
  if (phase !== 'dragging' || !source) { dragPlan.value = null; return }
  dragPlan.value = planTabDrop({
    geometry: geometry.value,
    model: controller.model.value,
    point,
    source,
  })
}

function onDragUp() {
  detachDrag()
  const wasPending = dragMachine.phase === 'pending'
  const pendingSource = dragMachine.source
  const plan = dragPlan.value
  dragPlan.value = null
  dragPhase.value = 'idle'
  dragMachine.up(plan && plan.kind !== 'none' ? () => applyPlan(plan) : undefined)
  // user:“我点切换标签页没有反应 为什么”+(按下到松手未超过拖拽阈值时视为点击，即使指针轻微滑出标签外沿也照常切换标签)
  if (wasPending && pendingSource) {
    controller.activate(pendingSource.pane, pendingSource.surfaceId)
  }
}

function onDragCancel() {
  detachDrag()
  dragPlan.value = null
  dragPhase.value = 'idle'
  dragMachine.cancel()
}

function detachDrag() {
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragUp)
  window.removeEventListener('pointercancel', onDragCancel)
}

const dropRect = computed<Rect | null>(() => {
  const plan = dragPlan.value
  return plan ? dropPreview(plan, geometry.value) : null
})

// ---------------------------------------------------------------------------
// 键盘：唯一来源是 keyboardIntent（不再第二份映射）
// ---------------------------------------------------------------------------
function activeArea() {
  return areas.value.find(entry => entry.area.id === controller.state.activePane) ?? areas.value[0] ?? null
}

function onKeydown(event: KeyboardEvent) {
  // user:“键盘单一来源”+(映射表在 useWorkspace 的 keyboardIntent 里；这里只负责执行)。
  const intent = keyboardIntent({
    key: event.key,
    ctrlKey: event.ctrlKey,
    metaKey: event.metaKey,
    shiftKey: event.shiftKey,
    altKey: event.altKey,
  })
  if (!intent) return
  if (intent.kind === 'split') {
    event.preventDefault()
    controller.split(controller.state.activePane, intent.edge)
    return
  }
  if (intent.kind === 'close-aux') {
    const current = activeArea()
    if (current && current.area.role !== 'main') { event.preventDefault(); controller.closePane(current.area.id) }
    return
  }
  if (intent.kind === 'select-area') {
    const target = areas.value[intent.index]
    if (target) { event.preventDefault(); controller.state.activePane = target.area.id }
    return
  }
  if (intent.kind === 'cycle-tab') {
    const current = activeArea()
    if (current && current.tabs.length > 1) {
      event.preventDefault()
      const index = current.tabs.findIndex(tab => tab.id === current.area.active)
      const next = current.tabs[(index + (intent.reverse ? current.tabs.length - 1 : 1)) % current.tabs.length]
      if (next) controller.activate(current.area.id, next.id)
    }
    return
  }
  if (intent.kind === 'escape' && dragMachine.phase !== 'idle') {
    event.preventDefault()
    onDragCancel()
  }
}

onMounted(() => {
  measure()
  schedule()
  emitShellStyle()
  if (typeof ResizeObserver !== 'undefined' && root.value) {
    observer = new ResizeObserver(schedule)
    observer.observe(root.value)
  }
  window.addEventListener('resize', schedule, { passive: true })
})
onBeforeUnmount(() => {
  if (frame && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(frame)
  cancelDivider()
  observer?.disconnect()
  observer = null
  window.removeEventListener('resize', schedule)
  detachDrag()
})

// user:“会话无法显示了，排查一下”+(不能直接把 rect 对象 .join('|') 成 "[object Object]"，否则窗口尺寸变化时 watch 永不触发，主区停留在 0x0 且 visibility:hidden)
watch(
  () => [
    String(controller.state.hidden),
    areas.value.map(entry => {
      const r = entry.geometry?.rect
      return r ? `${r.x},${r.y},${r.width},${r.height}` : ''
    }).join('|'),
    controller.floats.value.map(f => `${f.tab.id}:${f.yieldEnabled}:${f.rect.x},${f.rect.y},${f.rect.width},${f.rect.height}`).join('|'),
    liveComposedFloatHoles.value.map(h => `${h.x},${h.y},${h.width},${h.height}`).join('|'),
  ].join('||'),
  () => emitShellStyle(),
)
watch(
  () => `${controller.state.mainTab?.id ?? ''}|${controller.state.hidden}|${areas.value.length}|${controller.floats.value.length}`,
  () => { void nextTick(measure) },
)
</script>

<template>
  <div
    ref="root"
    class="ws2-root"
    :class="{ 'ws2-root--hidden': controller.state.hidden, 'ws2-root--tab-dragging': dragMachine.phase === 'dragging' }"
    data-ws2-root
    tabindex="0"
    @keydown="onKeydown"
  >
    <CoreWorkspaceArea
      v-for="entry in areas"
      :key="entry.area.id"
      :area-id="entry.area.id"
      :axis="entry.geometry?.chrome.tabbar === 'hidden' ? 'vertical' : 'horizontal'"
      :origin="rootOrigin"
      :rect="entry.geometry?.rect ?? { x: 0, y: 0, width: 0, height: 0 }"
      :content-rect="entry.geometry?.contentRect ?? { x: 0, y: 0, width: 0, height: 0 }"
      :tabs="entry.tabs"
      :active-id="entry.area.active"
      :compact="controller.model.value.prefs.compact"
      :tabbar="entry.geometry?.chrome.tabbar ?? 'full'"
      :cutout-holes="liveComposedFloatHoles"
      :window-top-gap="entry.geometry?.rect.y === 0 ? Math.max(0, windowWidth - rootOrigin.x - entry.geometry.rect.x - entry.geometry.rect.width) : undefined"
      @select="controller.activate(entry.area.id, $event)"
      @close="(surfaceId: string) => onCloseTab(entry, surfaceId)"
      @close-pane="controller.closePane(entry.area.id)"
      @tab-pointerdown="(surfaceId: string, event: PointerEvent) => onTabPointerDown(entry.area.id, surfaceId, event)"
      @unpin="controller.unpinCommit(entry.area.id)"
      @add="controller.add('browser', '', '新标签', entry.area.id)"
      @rename="(id: string, title: string) => controller.updateTabMetadata(id, { title })"
      @content-target="setTarget(`area:${entry.area.id}`, $event)"
    />

    <div
      v-for="view in dividers"
      :key="`divider-${view.path.join('-')}`"
      class="ws2-divider"
      :class="`ws2-divider--${view.direction}`"
      :style="{
        left: `${view.strip.x}px`, top: `${view.strip.y}px`,
        width: `${view.strip.width}px`, height: `${view.strip.height}px`,
        clipPath: buildCutoutClipPath(view.strip, liveComposedFloatHoles),
      }"
      role="separator"
      :aria-orientation="view.direction === 'row' ? 'vertical' : 'horizontal'"
      data-ws2-divider
      @pointerdown="onDividerDown(view, $event)"
      @pointermove="onDividerMove"
      @pointerup="onDividerUp"
      @pointercancel="onDividerUp"
      @dblclick="onDividerDouble(view)"
    ></div>

    <CoreWorkspaceFloat
      v-for="entry in controller.floats.value"
      :key="entry.tab.id"
      :tab="entry.tab"
      :rect="entry.rect"
      :cutout-holes="floatCutouts.get(entry.tab.id)"
      :origin="rootOrigin"
      :active="controller.floatFocus.value === entry.tab.id"
      :yield-enabled="entry.yieldEnabled"
      :preview="controller.pinPreview.value?.surfaceId === entry.tab.id ? controller.pinPreview.value.rect : null"
      @focus="controller.focusFloat(entry.tab.id)"
      @close="onPinHover(entry.tab.id, false); controller.collapseFloat(entry.tab.id)"
      @pin="onPinCommit(entry.tab.id)"
      @pin-hover="onPinHover(entry.tab.id, $event)"
      @toggle-yield="controller.setFloatYieldEnabled(entry.tab.id, $event)"
      @begin-drag="controller.beginInteraction('floating')"
      @end-drag="controller.endInteraction()"
      @rect-change="controller.moveFloat(entry.tab.id, $event)"
      @content-target="setTarget(`float:${entry.tab.id}`, $event)"
    />

    <CoreWorkspaceContentHost
      v-for="entry in placedContent"
      :key="entry.tab.id"
      v-bind="entry"
    >
      <template #default="content"><slot v-bind="content" /></template>
    </CoreWorkspaceContentHost>

    <!-- 固定落位预览：鼠标悬浮「固定」时在工作区里画出一块半透明虚线骨架，提前标明分屏后会落在哪里。 -->
    <div
      v-if="controller.pinPreview.value"
      class="ws2-pin-preview"
      data-ws2-pin-preview
      aria-hidden="true"
      :style="{
        position: 'absolute',
        left: `${controller.pinPreview.value.rect.x}px`,
        top: `${controller.pinPreview.value.rect.y}px`,
        width: `${controller.pinPreview.value.rect.width}px`,
        height: `${controller.pinPreview.value.rect.height}px`,
        background: 'color-mix(in srgb, var(--blue, #3b82f6) 18%, transparent)',
        border: '2px dashed color-mix(in srgb, var(--blue, #3b82f6) 88%, transparent)',
        boxSizing: 'border-box',
        borderRadius: 'var(--radius)',
        pointerEvents: 'none',
        zIndex: 'calc(var(--z-composer, 40) + 2)',
      }"
    ></div>

    <!-- 落点预览：骨架虚影，提示标签将被投放到哪个区域/浮窗，拖动期间原生网页已让位，不会被遮挡。 -->
    <div
      v-if="dropRect"
      class="ws2-drop-preview"
      data-ws2-drop-preview
      aria-hidden="true"
      :style="{
        position: 'absolute',
        left: `${dropRect.x}px`,
        top: `${dropRect.y}px`,
        width: `${dropRect.width}px`,
        height: `${dropRect.height}px`,
        background: 'color-mix(in srgb, var(--theme-main-text) 10%, transparent)',
        border: '2px dashed color-mix(in srgb, var(--theme-main-text) 55%, transparent)',
        boxSizing: 'border-box',
        borderRadius: 'var(--radius)',
        pointerEvents: 'none',
        zIndex: 50,
      }"
    ></div>


  </div>
</template>
