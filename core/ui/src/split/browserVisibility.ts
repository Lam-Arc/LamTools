// user:“网页不能盖住 Sunday 的菜单、浮层，标签切换也不能跑到屏幕角落”+(可见性判定收敛成一个纯函数，穷举组合用单测盯住)。
//
// 原生子 webview 永远画在 HTML 之上，所以只要有任何一层浮在网页宿主之上，就必须把网页隐藏；
// 反过来，任一条“不该显示”的条件成立时如果还显示着，用户看到的就是网页盖住菜单。

import type { InteractionPhase } from '@/workspace/interaction'

export interface BrowserHostRect {
  x: number
  y: number
  width: number
  height: number
}

export interface BrowserVisibilityInput {
  /** 宿主元素相对窗口的矩形；null 表示还没挂载。 */
  host: BrowserHostRect | null
  /** 所在分屏是否可见（工作区没收起、也不在聚焦别的屏）。 */
  paneVisible: boolean
  /** 当前这个标签是否是所在分屏的活动标签。 */
  tabActive: boolean
  /** 整个分屏工作区是否收起。 */
  workspaceHidden: boolean
  /** 右键菜单/下拉等浮层是否打开。 */
  overlayOpen: boolean
  // user:“BrowserVisibilityInput 的 resizing 扩成 interacting（resizing|draggingTab|splitPulling|swapping）”+
  // (拖标签、拉角柄、交换屏的时候，布局每一帧都在变，网页必须让位——不只是“正在拉分隔条”这一种)。
  /** 当前进行中的指针交互；'none' 或省略表示没有交互。 */
  interacting?: InteractionPhase
  // user:“保留 browserVisibility.resizing：兼容字段、仅测试在用。不要删，但加注释标 @deprecated 用 interacting，
  // 并确保生产侧没有新的 resizing: 传参”+
  // (它只是 interacting === 'resizing' 的旧写法，唯一用途是让老测试不必改；新代码一律传 interacting)。
  /** @deprecated 用 interacting（interacting: 'resizing' 等价）。仅保留兼容，生产侧不再传入。 */
  resizing?: boolean
  /** 是否有模态/右栏/浮层实际盖在宿主矩形上。 */
  obscured: boolean
  // user:“悬浮窗：…点击外部不关闭，只置顶/置底切换”+
  // (置底 = 网页先让开、框还留着：原生网页永远画在 DOM 之上，想让它真正退到后面只能不显示它)。
  /** 用户把网页“置底”了：框还在，但网页此刻不该显示。 */
  suppressed?: boolean
}

/** 只有一种交互会让网页让位：任何非 none 的指针手势。 */
export function interactionHidesBrowser(phase: InteractionPhase | undefined): boolean {
  return Boolean(phase) && phase !== 'none'
}


/**
 * user:“可见性是一个纯函数…让位改成单一登记口…交互相位只影响会重排布局的手势”+
 * (V2-B：`browserVisible` 是唯一可见性判定。入参全部来自布局与登记口，
 *  不再读 DOM；`floating`（浮层拖动/缩放）必须跟手，不隐藏。)
 */
export type BrowserLayoutPhase = 'idle' | 'draggingTab' | 'resizingDivider' | 'movingArea' | 'floating'

export interface BrowserVisibleInput {
  /** 布局算出的内容区矩形（CSS px）；null = 还没有 rect。 */
  rect: { width: number; height: number } | null
  /** 所在 Area 是否可见（工作区没收起、也没被聚焦到别的屏）。 */
  areaVisible: boolean
  /** 已登记的浮层数量（唯一登记口：split/browserOverlays.ts）。 */
  overlayCount: number
  /** 当前交互相位。 */
  phase: BrowserLayoutPhase
}

/**
 * user:“只有会重排布局的三种手势才让网页让位”+(拖标签 / 拉分隔条 / 区域重停靠)；
 * `idle` 与 `floating` **不**隐藏——浮层拖动必须跟手，否则网页一抖一抖。
 */
export function phaseHidesBrowser(phase: BrowserLayoutPhase): boolean {
  return phase === 'draggingTab' || phase === 'resizingDivider' || phase === 'movingArea'
}

/**
 * user:“分屏拖动手感不佳，卡顿/不跟手”+
 * (控制器的交互相位是 WorkspacePhase（`resizingDivider`/`movingArea`），旧映射只认 `resizing`，
 *  于是拉分隔条时网页根本没让位，一直用 IPC 追矩形。两个类型不同源，映射只写这一处)。
 */
export function layoutPhaseOfController(phase: string | null | undefined): BrowserLayoutPhase {
  switch (phase) {
    case 'draggingTab': return 'draggingTab'
    case 'resizingDivider':
    case 'resizing': return 'resizingDivider'
    case 'movingArea':
    case 'splitPulling':
    case 'swapping': return 'movingArea'
    case 'floating': return 'floating'
    default: return 'idle'
  }
}

/**
 * 唯一可见性判定（纯函数，无副作用）。
 *
 * 规约：`rect` 缺失或宽高 <1 → 不可见；`areaVisible=false` → 不可见；
 * `overlayCount>0` → 不可见（浮层必须盖住网页）；只有三种重排手势会让位。
 */
export function browserVisible(input: BrowserVisibleInput): boolean {
  const rect = input.rect
  if (!rect) return false
  if (!(rect.width >= 1) || !(rect.height >= 1)) return false
  if (!input.areaVisible) return false
  if (input.overlayCount > 0) return false
  return !phaseHidesBrowser(input.phase)
}

export interface BrowserBounds {
  x: number
  y: number
  width: number
  height: number
  visible: boolean
}

/** 宿主是否真的占着屏幕上一块地方。 */
export function hostHasArea(host: BrowserHostRect | null): host is BrowserHostRect {
  return browserAreaIssue(host) === null
}

/**
 * user:“输入地址后网页区域无效/空白”+(宿主到底有没有能画网页的地方；没有时给出可读原因，
 *  而不是把 1×1 的隐藏矩形当成“已经显示”)。
 * unmounted=宿主还没挂载，collapsed=这块分屏现在真的没有尺寸（窗口太窄、分屏被折叠）。
 */
export type BrowserAreaIssue = 'unmounted' | 'collapsed'

export function browserAreaIssue(host: BrowserHostRect | null): BrowserAreaIssue | null {
  if (!host) return 'unmounted'
  return host.width > 0 && host.height > 0 ? null : 'collapsed'
}

/**
 * 唯一真源：把布局矩形 + 浮层状态 + 标签状态算成 Rust 侧要执行的 bounds。
 * 只要有一条“不该显示”成立，就一定 visible=false，且宽高至少 1（WebView2 拒绝 0 尺寸）。
 */
export function resolveBrowserBounds(input: BrowserVisibilityInput): BrowserBounds {
  const host = input.host
  const width = Math.max(1, Math.round(host?.width ?? 1))
  const height = Math.max(1, Math.round(host?.height ?? 1))
  const position = {
    x: Math.max(0, Math.round(host?.x ?? 0)),
    y: Math.max(0, Math.round(host?.y ?? 0)),
    width,
    height,
  }
  const visible = hostHasArea(host)
    && input.paneVisible
    && input.tabActive
    && !input.workspaceHidden
    && !input.overlayOpen
    && !interactionHidesBrowser(input.interacting)
    && !input.resizing
    && !input.obscured
    && !input.suppressed
  return { ...position, visible }
}

/** 序列化去重：同一份 bounds 不重复下发给 Rust。 */
export function serializeBounds(bounds: BrowserBounds): string {
  return JSON.stringify(bounds)
}
