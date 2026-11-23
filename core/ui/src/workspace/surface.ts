// user:“还有浏览器的页显示应当可以设比例，而不是死板的填充分屏，以及包括分屏这个概念也是 分屏是为了便于交互，
// 如果有什么其他的你认为在 Sunday 中可以便于交互的方式，也可以自行设计，比如灯箱、分屏、全屏（agent 退居）、悬浮窗等，
// 自由设计，目的是易用，第一性原则”+
// (先回答“用户和内容打交道的意图有几种”，再决定“形态有几种”。结论是三种可写意图——
//  同时看（分屏）/ 只看它（聚焦全屏）/ 瞥一眼（悬浮窗）——加上只读确认用的灯箱，正好四种、不再多。
//  这个文件只放纯逻辑：浮窗矩形、内缩、约束、缩放归一化；组件只负责把结论变成一次 CSS 布局和一次 browser_bounds。)

/** 用户和内容打交道的三种可写意图；只读确认由既有的灯箱（PreviewLightbox）承担，不放进这里。 */
export type SurfaceMode = 'split' | 'focus' | 'float'

/** 浮窗外框在屏幕上的矩形（DOM 画边框、圆角、阴影用的那个框）。 */
export interface SurfaceFrame { x: number; y: number; width: number; height: number }
export interface SurfaceViewport { width: number; height: number }

// user:“悬浮窗：可拖动、可缩放的小窗…原生 webview 没有圆角与阴影，所以浮窗外观要用 DOM 边框 + 内缩（webview 区域略小于外框）”+
// (网页矩形四边都往内让这么多，DOM 的边框、圆角、阴影才有地方露在网页外面——这是浮窗看起来“是一个窗口”的唯一手段)。
export const FLOAT_FRAME_INSET = 8
export const FLOAT_MIN_WIDTH = 320
export const FLOAT_MIN_HEIGHT = 200
export const FLOAT_VIEWPORT_MARGIN = 12
/** 浮窗默认落点要给主区输入框留出的高度：浮窗是“瞥一眼”，不该压住正在打字的地方。 */
export const FLOAT_COMPOSER_RESERVE = 132

// user:“全屏（agent 退居）…对话退居为可输入的窄条或可呼出的浮层”+
// (这条窄条是聚焦全屏时 Agent 唯一还露在外面的地方：够放一个输入框，其余全部让给内容)。
export const FOCUS_STRIP_HEIGHT = 96

/** 服务端 browser_zoom 的同一套上下限；脏数据一律回落到 1。 */
export const ZOOM_MIN = 0.25
export const ZOOM_MAX = 5

const clampNumber = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

/**
 * 形态本身不持久化。
 * user:“自由设计，目的是易用”+(重启后回到分屏：开机就被锁在全屏里、找不到对话，是把便利做成了陷阱)。
 */
export function initialSurface(): SurfaceMode { return 'split' }

/** 工具栏那一个按钮按顺序在三种形态间轮转（分屏 → 全屏 → 悬浮 → 分屏）。 */
export function cycleSurface(mode: SurfaceMode): SurfaceMode {
  return mode === 'split' ? 'focus' : mode === 'focus' ? 'float' : 'split'
}

/**
 * 浮窗最小尺寸必须容得下“内缩一圈 + 一条拖动把手”，否则网页会被挤成一条缝。
 * 这条不变量由测试盯着，样式里的内边距和这里的常量是同一个来源。
 */
export function floatFrameFits(frame: SurfaceFrame): boolean {
  return frame.width >= FLOAT_MIN_WIDTH && frame.height >= FLOAT_MIN_HEIGHT
}

/**
 * 把浮窗夹在视口里：宽高至少到最小值，位置不让外框跑出屏幕。
 * 拖动、缩放、窗口变小三种情况全部走这一个函数，浮窗不会出现“拖到屏幕外再也点不到”。
 */
export function clampFloatFrame(frame: SurfaceFrame, viewport: SurfaceViewport): SurfaceFrame {
  const viewportWidth = Math.max(1, Math.round(viewport.width))
  const viewportHeight = Math.max(1, Math.round(viewport.height))
  const width = clampNumber(Math.round(frame.width), Math.min(FLOAT_MIN_WIDTH, viewportWidth), viewportWidth)
  const height = clampNumber(Math.round(frame.height), Math.min(FLOAT_MIN_HEIGHT, viewportHeight), viewportHeight)
  return {
    x: clampNumber(Math.round(frame.x), 0, Math.max(0, viewportWidth - width)),
    y: clampNumber(Math.round(frame.y), 0, Math.max(0, viewportHeight - height)),
    width,
    height,
  }
}

/**
 * 默认落点：右下角、按视口比例取一个“够看但不喧宾夺主”的尺寸，并上抬一截把输入框让出来。
 * 用户第一次点“悬浮窗”就能直接用，不需要先自己摆一次位置。
 */
export function defaultFloatFrame(viewport: SurfaceViewport): SurfaceFrame {
  const viewportWidth = Math.max(1, Math.round(viewport.width))
  const viewportHeight = Math.max(1, Math.round(viewport.height))
  const available = Math.max(1, viewportWidth - FLOAT_VIEWPORT_MARGIN * 2)
  const width = clampNumber(Math.round(viewportWidth * 0.42), Math.min(FLOAT_MIN_WIDTH, available), Math.min(640, available))
  const height = clampNumber(
    Math.round(viewportHeight * 0.52),
    Math.min(FLOAT_MIN_HEIGHT, Math.max(1, viewportHeight - FLOAT_VIEWPORT_MARGIN * 2)),
    520,
  )
  return clampFloatFrame({
    x: viewportWidth - width - FLOAT_VIEWPORT_MARGIN,
    y: viewportHeight - height - FLOAT_VIEWPORT_MARGIN - FLOAT_COMPOSER_RESERVE,
    width,
    height,
  }, viewport)
}

/** 拖动：只改位置，尺寸由 clampFloatFrame 一起兜住。 */
export function moveFloatFrame(frame: SurfaceFrame, delta: { dx: number; dy: number }, viewport: SurfaceViewport): SurfaceFrame {
  return clampFloatFrame({ ...frame, x: frame.x + delta.dx, y: frame.y + delta.dy }, viewport)
}

/** 右下角拉拽：只改尺寸，位置不动（左上角锚点固定在用户摆好的地方）。 */
export function resizeFloatFrame(frame: SurfaceFrame, delta: { dx: number; dy: number }, viewport: SurfaceViewport): SurfaceFrame {
  return clampFloatFrame({ ...frame, width: frame.width + delta.dx, height: frame.height + delta.dy }, viewport)
}

/**
 * user:“不打断当前布局…不遮输入框（或可一键置底）”+
 * (浮窗是“瞥一眼”，不是“占住屏幕”：先夹进给它的活动区域，再确保它没有压到输入框上沿。
 *  压到了就往上收高度，而不是把用户刚摆好的位置挪走——挪位置会让人以为自己没拖动成功)。
 */
export function fitFloatFrame(frame: SurfaceFrame, viewport: SurfaceViewport, bottomLimit = 0): SurfaceFrame {
  return clampFrameTopLimit(clampFloatFrame(frame, viewport), bottomLimit)
}

/**
 * user:“独立页面缩放：工具栏提供缩放（与 browser_zoom 已有命令对接），并与 pane 比例分开记忆”+
 * (比例是分屏树里的 ratio、缩放是标签自己的 zoom，两件事分开存；这里只把 zoom 归一化，脏数据回落 1)。
 */
export function normalizeZoom(value: unknown): number {
  const number = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(number)) return 1
  return Math.round(clampNumber(number, ZOOM_MIN, ZOOM_MAX) * 100) / 100
}

/** 工具栏上的缩放读数（“110%”）；缩放是独立于 pane 比例的另一件事，必须看得见。 */
export function zoomPercent(zoom: number): string {
  return `${Math.round(normalizeZoom(zoom) * 100)}%`
}

/** 窄条矩形：聚焦全屏时对话退居到工作区底部这一条，其余空间全给内容。 */
export function focusStripRect(viewport: SurfaceViewport, composerInset = 0, expanded = false): SurfaceFrame {
  const height = focusStripHeight(viewport.height, composerInset, expanded)
  return { x: 0, y: Math.max(0, Math.round(viewport.height) - height), width: Math.max(0, Math.round(viewport.width)), height }
}

/**
 * 聚焦全屏时各个屏的显示矩形：内容屏铺满，其余屏消失，主区（对话）退到底部窄条。
 * user:“全屏（agent 退居）…对话退居为可输入的窄条”+
 * (唯一的例外是内容本身就住在主区：那时主区没有第二块地方可以退居，
 *  只能让主区自己铺满，对话只剩输入框那一条——网页矩形由 clampedHostRect 按输入框真实上沿收住，
 *  否则“铺满”就是把输入框盖掉)。
 */
export function focusPaneRects(paneIds: string[], focusPane: string, focusRect: SurfaceFrame, stripRect: SurfaceFrame): Record<string, SurfaceFrame> {
  const panes: Record<string, SurfaceFrame> = {}
  for (const id of paneIds) panes[id] = { x: 0, y: 0, width: 0, height: 0 }
  panes[focusPane] = focusRect
  if (focusPane !== 'main') panes.main = stripRect
  return panes
}

/**
 * user:“全屏时输入框可用…原生 webview 的 bounds 必须跟着窗口尺寸变化同步，不能出现「网页盖住输入框」”+
 * (输入框现在是浮在同一块内容上的 DOM，原生网页永远画在 DOM 之上——所以窄条必须按输入框的**真实**高度算，
 *  而不是一个拍出来的常数：多行、附件托盘、排队面板都会把输入框顶高，常数迟早会盖住它)。
 */
export const FOCUS_STRIP_PADDING = 32

/** 输入框上沿距离内容区底边还有多少像素；拿不到测量值时返回 0（按常数兜底）。 */
export function composerInsetFromTop(composerTop: number, viewportHeight: number): number {
  if (!(composerTop > 0) || !(viewportHeight > 0)) return 0
  return Math.max(0, Math.round(viewportHeight - composerTop))
}

/**
 * 聚焦全屏时底部窄条的高度：至少能装下输入框，展开时给到四成；任何情况下都不超过六成，
 * 否则“全屏”就变成了“聊天”。
 */
export function focusStripHeight(contentHeight: number, composerInset = 0, expanded = false): number {
  const height = Math.max(0, Math.round(contentHeight))
  if (!height) return 0
  const base = expanded ? Math.max(FOCUS_STRIP_HEIGHT, Math.round(height * 0.4)) : FOCUS_STRIP_HEIGHT
  const needed = composerInset > 0 ? composerInset + FOCUS_STRIP_PADDING : 0
  return Math.min(Math.max(base, needed, FOCUS_STRIP_HEIGHT), Math.round(height * 0.6), height)
}

/**
 * 把矩形压到某条水平线之上（聚焦全屏时用输入框上沿当这条线）。
 * 这是“网页永不盖住输入框”的最后一道保险：即使窄条算小了，网页也会自己让开。
 */
export function clampFrameTopLimit(frame: SurfaceFrame, topLimit: number, gap = 8): SurfaceFrame {
  const limit = Math.round(topLimit) - gap
  if (!(topLimit > 0) || frame.y + frame.height <= limit) return frame
  return { ...frame, height: Math.max(1, Math.round(limit - frame.y)) }
}

/**
 * 同一种“离开分屏网格”的形态里，只有「聚焦全屏」必须独占：它靠把内容铺满整块工作区来占地方，
 * 两份同时成立时谁盖谁无法解释。
 * user:“浮层不参与矩形分屏、可多开；浮层层级用 z 序管理”+(浮层各自有矩形，可以并存：
 * 新开一个浮层不再把别的浮层踢回分屏，先后关系交给 floatOrder)。
 * 返回需要被复位成 split 的其它标签 id。
 */
export function exclusiveSurfaceOwners(tabs: Array<{ id: string; surface?: SurfaceMode }>, keep: string): string[] {
  return tabs.filter(tab => tab.id !== keep && tab.surface === 'focus').map(tab => tab.id)
}

// user:“要让「分屏 / 聚焦全屏 / 悬浮」三态在任何内容类型上都可判读（对不支持形态的内容，按钮置灰并给原因，不要点了没反应）”+
// (能离开分屏网格的只有真装了网页的标签：编辑器/预览/页面还没有形态实现，空浏览器标签没有网页可搬。
//  这里一次算清“能不能”和“为什么不能”，按钮、菜单、快捷键都读这一份结论，谁也不会各说一套)。
export type SurfaceBlockReason = 'not-browser' | 'no-page'

export interface SurfaceAvailability {
  /** 分屏永远成立：它是不动任何东西的默认形态。 */
  readonly split: true
  readonly focus: boolean
  readonly float: boolean
  /** 不能离开分屏时为原因码；能离开时是 null。文案由组件翻译，纯逻辑不碰 i18n。 */
  readonly reason: SurfaceBlockReason | null
}

export function surfaceAvailability(tab: { kind?: string; resource?: string }): SurfaceAvailability {
  const browser = tab.kind === 'browser'
  const page = Boolean(String(tab.resource ?? '').trim())
  const canLeave = browser && page
  return { split: true, focus: canLeave, float: canLeave, reason: canLeave ? null : browser ? 'no-page' : 'not-browser' }
}

/**
 * 按了快捷键就轮转三态，但绝不落进一个摆不出来的形态：
 * 不支持的内容停在分屏（同时由界面给出原因），而不是切过去变成一张空白或错位的屏。
 */
export function cycleSurfaceForTab(mode: SurfaceMode, tab: { kind?: string; resource?: string }): SurfaceMode {
  return surfaceAvailability(tab).focus ? cycleSurface(mode) : 'split'
}
