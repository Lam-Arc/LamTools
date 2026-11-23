/**
 * 工作区注入键（V2-C1）。
 *
 * user:“在 CoreWorkspaceArea.vue 里把 contentRect 通过 provide/props 传下去，并在
 * CoreSplitBrowser 的调用点旁留一个 TODO 说明 V2-C2 会接”+
 * (矩形唯一来源是引擎；内容组件不该再量宿主。这里把 Area 的 contentRect 放进注入，
 *  让 V2-C2 的浏览器/预览器能直接读，不必各自 getBoundingClientRect)。
 */
import type { ComputedRef, InjectionKey } from 'vue'
import type { Rect } from '@/workspace'

/** 当前区域内容区（CSS px，相对工作区原点）。 */
export const WORKSPACE_CONTENT_RECT: InjectionKey<ComputedRef<Rect>> = Symbol('workspace-content-rect')

/** 一块区域的两个矩形：内容区（下发用）与区域完整矩形（越界求交的 host）。 */
export interface AreaRects {
  contentRect: Rect
  hostRect: Rect
}

/**
 * user:“按 tab 的 surfaceId 提供查询函数，让子内容能拿到「属于我的那个矩形」”+
 * (V2-C1b：矩形唯一来源是引擎。区域 provide 一个 `(surfaceId) => AreaRects | null`，
 *  浏览器组件据此下发，不再自己 `getBoundingClientRect()`。)
 */
export const WORKSPACE_AREA_RECT: InjectionKey<(surfaceId: string) => AreaRects | null> = Symbol('workspace-area-rect')

/** user:“快速精准高效的解决”+(布局壳提供落点和实时矩形，内容实例独立保活)。 */
export interface WorkspaceContentTarget {
  element: HTMLElement
  rects: () => AreaRects
}

/** user:“网页层级不正确”+(网页用自己提交给原生层的显示矩形登记镂空)。 */
export const WORKSPACE_COMPOSED_RECT: InjectionKey<(id: string, rect: Rect | null) => void> = Symbol('workspace-composed-rect')
