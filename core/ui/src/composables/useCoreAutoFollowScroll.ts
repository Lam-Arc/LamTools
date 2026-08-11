import { nextTick, ref, type Ref } from 'vue'

/**
 * Core 自动跟随滚动 —— 容器级控制器（单通道统一实现）
 *
 * 设计要点（对应易错点清单 A–E 全部 20 条）：
 *
 * A. 状态语义
 *  - `autoFollow`（"是否应该跟随新内容"的意图）与 `atBottom`（"视口当前是否在底部"
 *    的实测位置）是两个独立状态；类比：用户正读历史时 intent=false 但位置可能是底部，
 *    force 滚动后 intent=true 但位置仍可能短暂非底部。
 *  - 任何滚动方式（滚轮/拖条/触控板/键盘/程序化）都必须能开关跟随——`handleScroll`
 *    是唯一事实来源（双向），wheel 只做"立即抢占"。
 *  - 滚轮向上（deltaY<0）立即置 false，不等 scroll 事件（wheel 先于 scroll 触发），
 *    否则下一次 tick 会把用户拉回。
 *
 * B. 时序与异步
 *  - 滚动永远在 DOM 更新之后执行（nextTick / afterFrame），否则 scrollHeight 是旧值。
 *  - 单写 scrollTop：一帧最多一次目标写；帧后仅当 scrollHeight 实际变大才二次校正，
 *    绝不逐帧无条件双写（旧版卡顿根因之一）。
 *  - token 竞态防护：每次 scrollToBottom 生成自增 seq，await 后 seq 仍匹配才写 DOM，
 *    旧调用自然作废，不会用旧值覆盖新值。
 *  - reset()：切会话/重开对话框统一重置 intent/位置/自动滚动 token。
 *
 * C. 观察器
 *  - 由消费方负责 ResizeObserver（观察滚动容器 + 直接子元素），回调只调
 *    scrollToBottom()；控制器不重复观察，避免多通道堆叠。
 *
 * D. 程序化滚动防误伤（易错点 16）
 *  - force/正常滚动写 scrollTop 会同步触发 scroll 事件；若 handleScroll 在"不在底部"
 *    时直接关跟随，一次滚动中间态（scrollTop 尚未到顶）就会把 autoFollow 误关。
 *    解决：写之前置 scrollingProgrammatically=true，下一次 handleScroll 消费后清除；
 *    且 handleScroll 用归一化位置钳制（scrollTop 超出 [0, max] 按端点算），
 *    保证"目标就是底部"的滚动在到达后仍判为 nearBottom。
 */

export const CORE_SCROLL_BOTTOM_THRESHOLD_PX = 80

export interface CoreScrollableElement {
  scrollHeight: number
  scrollTop: number
  clientHeight: number
  scrollTo?: (options: ScrollToOptions) => void
}

export interface UseCoreAutoFollowScrollOptions {
  bottomThresholdPx?: number
  /** DOM 更新完成的钩子（默认 nextTick），通常注入 nextTick 前后都要滚的场景 */
  afterDomUpdate?: () => Promise<void>
  /** 一帧之后的钩子（默认 rAF），用于二次校正前等布局稳定 */
  afterFrame?: () => Promise<void>
  /** 是否启用平滑滚动（默认跟随系统 prefers-reduced-motion） */
  smoothEnabled?: () => boolean
}

export interface CoreAutoFollowScrollController {
  /** 意图：是否应跟随新内容滚动 */
  autoFollow: Ref<boolean>
  /** 实测位置：视口是否在底部（驱动"回到最新"按钮） */
  atBottom: Ref<boolean>
  /** 滚轮事件（.passive 绑定）；deltaY<0 立即抢占关闭跟随 */
  handleWheel: (event: Pick<WheelEvent, 'deltaY'>) => void
  /** scroll 事件（.passive 绑定）；双向同步 autoFollow 与 atBottom */
  handleScroll: () => void
  /** 判断当前是否在底部（供 ResizeObserver 快速 gating） */
  isNearBottom: () => boolean
  /**
   * 滚动到底部。默认仅在 autoFollow 下执行；force=true 无条件立即执行。
   * behavior='smooth' 仅在未开启 reduceMotion 时平滑，强制时始终 auto 立即到位。
   * 返回 Promise，但调用方无需 await（内部含 token 竞态防护）。
   */
  scrollToBottom: (force?: boolean, behavior?: ScrollBehavior) => Promise<void>
  /** 重置为初始状态（切会话/重开对话框/首次挂载调用），丢弃进行中的自动滚动 */
  reset: () => void
}

const reduceMotionDefault = () =>
  typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** 归一化：scrollTop 被浏览器钳制在 [0, scrollHeight-clientHeight] 内，超界按端点算 */
function normalizedScrollTop(el: CoreScrollableElement): number {
  const max = Math.max(0, el.scrollHeight - el.clientHeight)
  if (el.scrollTop <= 0) return 0
  if (el.scrollTop >= max) return max
  return el.scrollTop
}

export function coreIsScrollNearBottom(
  element: Pick<CoreScrollableElement, 'scrollHeight' | 'scrollTop' | 'clientHeight'> | null | undefined,
  thresholdPx = CORE_SCROLL_BOTTOM_THRESHOLD_PX,
): boolean {
  if (!element) return true
  const top = normalizedScrollTop(element)
  const max = Math.max(0, element.scrollHeight - element.clientHeight)
  return max - top <= thresholdPx
}

export function useCoreAutoFollowScroll(
  elementRef: Ref<CoreScrollableElement | null>,
  options: UseCoreAutoFollowScrollOptions = {},
): CoreAutoFollowScrollController {
  const autoFollow = ref(true)
  const atBottom = ref(true)
  const bottomThresholdPx = options.bottomThresholdPx ?? CORE_SCROLL_BOTTOM_THRESHOLD_PX

  /** 程序化滚动进行中：下一次 handleScroll 消费后清除，期间不判定"离开底部" */
  let programmatic = false
  /** 竞态防护 token：每次 scrollToBottom 递增，只有最新的调用允许写 DOM */
  let seq = 0

  function isNearBottom(): boolean {
    return coreIsScrollNearBottom(elementRef.value, bottomThresholdPx)
  }

  function handleWheel(event: Pick<WheelEvent, 'deltaY'>) {
    // Wheel fires before the resulting scroll event, so on an upward swipe we
    // seize control immediately for a snappier feel. Downward scrolling near
    // the bottom will re-enable via the follow-up scroll event.
    if (event.deltaY < 0) {
      autoFollow.value = false
      atBottom.value = false
    }
  }

  function handleScroll() {
    // Scroll is the single source of truth: every input method (wheel,
    // scrollbar drag, trackpad, keyboard, programmatic) lands here.
    // Two-way sync: near bottom => follow; away => stop following.
    if (programmatic) {
      // This scroll event was produced by our own scrollToBottom; consume the
      // flag without judging distance (avoids a mid-scroll force incorrectly
      // disabling follow — 易错点 16).
      programmatic = false
      // Still sync atBottom with the actual landed position so the
      // "jump to latest" affordance stays truthful mid-flight.
      const near = isNearBottom()
      atBottom.value = near
      if (near) autoFollow.value = true
      return
    }
    const near = isNearBottom()
    autoFollow.value = near
    atBottom.value = near
  }

  async function scrollToBottom(force = false, behavior: ScrollBehavior = 'auto') {
    const mySeq = ++seq
    await (options.afterDomUpdate?.() ?? nextTick())
    if (seq !== mySeq) return // a newer call superseded us — 易错点 7
    const el = elementRef.value
    if (!el) return
    if (!force && !autoFollow.value) return

    const wantsSmooth = behavior === 'smooth'
      && !(options.smoothEnabled?.() ?? reduceMotionDefault())
    // Force rolls always land instantly, even when smooth was requested —
    // "回到最新" must be immediate (易错点 20).
    const effectiveSmooth = wantsSmooth && !force

    if (effectiveSmooth && typeof el.scrollTo === 'function') {
      const target = el.scrollHeight
      programmatic = true
      el.scrollTo({ top: target, behavior: 'smooth' })
      autoFollow.value = true
      atBottom.value = true
      return
    }

    programmatic = true
    el.scrollTop = el.scrollHeight
    // Single write per frame (易错点 5/6): only correct when content kept
    // growing past the first write — the stream tick case.
    await (options.afterFrame?.() ?? afterFrame())
    if (seq !== mySeq) return
    if (el.scrollTop !== el.scrollHeight) {
      el.scrollTop = el.scrollHeight
    }
    autoFollow.value = true
    atBottom.value = true
  }

  function reset() {
    // 易错点 8/18: discard any in-flight scroll, restore intent & position.
    seq++
    programmatic = false
    autoFollow.value = true
    atBottom.value = true
  }

  return { autoFollow, atBottom, isNearBottom, handleWheel, handleScroll, scrollToBottom, reset }
}

function afterFrame(): Promise<void> {
  if (typeof requestAnimationFrame !== 'function') return Promise.resolve()
  return new Promise(resolve => requestAnimationFrame(() => resolve()))
}