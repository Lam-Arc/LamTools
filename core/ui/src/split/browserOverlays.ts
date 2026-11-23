/**
 * 全局浮层登记：让原生子 webview 无条件让位（V2-B 起是**唯一登记口**）。
 *
 * user:“让位改为单一登记口：任何浮层（菜单/模态/右栏/浮窗/灯箱）打开时必须 openOverlay()，
 * 由工作区统一计数；未登记不算数”+
 * (WebView2 子 webview 永远画在 DOM 之上，z-index 无用。只要登记数 > 0，网页就先藏起来；
 *  嵌套计数保证「两层浮层叠着时，关掉一层仍藏着网页」。)
 *
 * **必须登记的位置清单**（新增浮层时按这张表核对，漏一个就会「网页盖住菜单」）：
 * 1. 菜单服务（`components/context-menu/context-menu.ts`）
 * 2. 右键菜单 / 地址栏下拉（同名菜单服务）
 * 3. 模态确认框（`CoreConfirmDialog` 一类）
 * 4. 右栏卡片 / 侧边面板
 * 5. 灯箱 / 图片预览
 * 6. 浮窗（非网页内容的浮动面板：拖动/缩放期间也要登记）
 * 7. 插件页弹层（插件 UI 的浮层）
 *
 * 判定真源仍是 `browserVisibility.browserVisible` 的 `overlayCount`（这里只负责计数）。
 */
import { computed, onBeforeUnmount, ref, shallowRef } from 'vue'

const depth = ref(0)
const stack = shallowRef<string[]>([])

/** 登记一层浮层；返回释放函数（重复调用只释放一次，避免卸载与手动关闭各扣一次）。 */
export function openOverlay(label = 'overlay'): () => void {
  depth.value += 1
  stack.value = [...stack.value, label]
  let released = false
  return () => {
    if (released) return
    released = true
    depth.value = Math.max(0, depth.value - 1)
    const index = stack.value.lastIndexOf(label)
    stack.value = index < 0 ? stack.value : stack.value.filter((_, position) => position !== index)
  }
}

/** 需要一个函数式入口时用这个（与返回的释放函数等价）。 */
export function closeOverlay(release: (() => void) | null | undefined): void {
  release?.()
}

/**
 * 浮层深度。
 *
 * user:“overlayDepth(): number”+(V2-B 契约要求可调用；同时保留 `.value` 读法给既有组件
 * ——`CoreSplitBrowser.vue` 现在读 `overlayDepth.value`，V2-C 统一改成函数调用后再删。
 * 用 `defineProperty` 而不是 `Object.assign`：`assign` 会把 getter 求值一次、冻成常量。)
 */
export const overlayDepth = (() => depth.value) as (() => number) & { readonly value: number }
Object.defineProperty(overlayDepth, 'value', { get: () => depth.value, enumerable: true })
export function overlayActive(): boolean { return depth.value > 0 }
/** 调试用：谁把网页藏起来了。 */
export function overlayLabels(): readonly string[] { return stack.value }

/**
 * 组件内的守卫：同一时刻只持有一层；卸载时自动释放，
 * 免得「菜单还开着、组件已经没了」把网页永久藏起来。
 */
export function useOverlayGuard() {
  let release: (() => void) | null = null
  const open = (label = 'overlay') => { release?.(); release = openOverlay(label) }
  const close = () => { release?.(); release = null }
  onBeforeUnmount(close)
  return { open, close }
}

/** 测试用：把计数清回 0。 */
export function resetBrowserOverlays(): void {
  depth.value = 0
  stack.value = []
}
