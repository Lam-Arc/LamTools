import { getCurrentScope, nextTick, onScopeDispose, ref, watch, type Ref } from 'vue'

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
 * C. 哨兵
 *  - 控制器统一用 IntersectionObserver 观察传入的底部哨兵；哨兵离开视口且跟随意图仍在时，
 *    自动调用 scrollToBottom()。内容高度、虚拟布局和容器 padding 不再参与底部推算。
 *
 * D. 程序化滚动防误伤（易错点 16）
 *  - force/正常滚动写 scrollTop 会同步触发 scroll 事件；若 handleScroll 在"不在底部"
 *    时直接关跟随，一次滚动中间态（scrollTop 尚未到顶）就会把 autoFollow 误关。
 *    解决：写之前置 scrollingProgrammatically=true，下一次 handleScroll 消费后清除；
 *    且 handleScroll 用归一化位置钳制（scrollTop 超出 [0, max] 按端点算），
 *    保证"目标就是底部"的滚动在到达后仍判为 nearBottom。
 */

export const CORE_SCROLL_BOTTOM_THRESHOLD_PX = 80
export const CORE_SCROLL_SENTINEL_VISIBLE_RATIO = 0.99
export const CORE_HISTORY_AUTO_LOAD_THRESHOLD_PX = 1280

export function coreHistoryAutoLoadThreshold(clientHeight: number): number {
  return Math.max(CORE_HISTORY_AUTO_LOAD_THRESHOLD_PX, Math.max(0, clientHeight) * 4)
}

export function coreShouldAutoLoadHistory(
  scrollTop: number,
  hasMoreHistory: boolean,
  loading: boolean,
  thresholdPx = CORE_HISTORY_AUTO_LOAD_THRESHOLD_PX,
): boolean {
  return hasMoreHistory && !loading && scrollTop <= thresholdPx
}

export function coreApplyHistoryScrollCeiling(
  scrollTop: number,
  ceiling: number | null,
  active: boolean,
): number {
  if (!active || ceiling === null) return scrollTop
  return Math.max(scrollTop, Math.max(0, ceiling))
}

export interface CoreScrollableElement {
  scrollHeight: number
  scrollTop: number
  clientHeight: number
  scrollTo?: (options: ScrollToOptions) => void
}

export interface CoreScrollSentinel {
  scrollIntoView: (options?: ScrollIntoViewOptions) => void
}

export interface UseCoreAutoFollowScrollOptions {
  bottomThresholdPx?: number
  /** 底部哨兵存在时，以它的可见性和 scrollIntoView 作为唯一吸底依据。 */
  sentinelRef?: Ref<CoreScrollSentinel | null>
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
  /** scroll 事件（.passive 绑定）；哨兵模式下只识别用户向上离开。 */
  handleScroll: () => void
  /** IntersectionObserver 回传底部哨兵是否进入吸底范围。 */
  handleSentinelVisibility: (visible: boolean) => void
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
function maxScrollTop(el: Pick<CoreScrollableElement, 'scrollHeight' | 'clientHeight'>): number {
  return Math.max(0, el.scrollHeight - el.clientHeight)
}

function normalizedScrollTop(el: CoreScrollableElement): number {
  const max = maxScrollTop(el)
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
  const max = maxScrollTop(element)
  return max - top <= thresholdPx
}

/**
 * `isIntersecting` only means that at least one pixel overlaps. When an
 * observer uses a near-full threshold, treating a partially clipped sentinel
 * as visible loses the only threshold crossing that should trigger follow.
 */
export function coreIsBottomSentinelVisible(
  entry: Pick<IntersectionObserverEntry, 'isIntersecting' | 'intersectionRatio'> | null | undefined,
  visibleRatio = CORE_SCROLL_SENTINEL_VISIBLE_RATIO,
): boolean {
  return Boolean(entry?.isIntersecting && entry.intersectionRatio >= visibleRatio)
}

export function useCoreAutoFollowScroll(
  elementRef: Ref<CoreScrollableElement | null>,
  options: UseCoreAutoFollowScrollOptions = {},
): CoreAutoFollowScrollController {
  const autoFollow = ref(true)
  const atBottom = ref(true)
  const bottomThresholdPx = options.bottomThresholdPx ?? CORE_SCROLL_BOTTOM_THRESHOLD_PX
  const sentinelRef = options.sentinelRef

  /** 程序化滚动进行中：下一次 handleScroll 消费后清除，期间不判定"离开底部" */
  let programmatic = false
  /** 竞态防护 token：每次 scrollToBottom 递增，只有最新的调用允许写 DOM */
  let seq = 0
  let sentinelVisible = true
  let lastScrollTop = elementRef.value ? normalizedScrollTop(elementRef.value) : 0
  let lastScrollHeight = elementRef.value?.scrollHeight ?? 0

  function isNearBottom(): boolean {
    if (sentinelRef?.value) return sentinelVisible
    return coreIsScrollNearBottom(elementRef.value, bottomThresholdPx)
  }

  function handleWheel(event: Pick<WheelEvent, 'deltaY'>) {
    // Wheel fires before the resulting scroll event, so on an upward swipe we
    // seize control immediately for a snappier feel. Downward scrolling near
    // the bottom will re-enable via the follow-up scroll event.
    if (event.deltaY < 0) {
      programmatic = false
      autoFollow.value = false
      atBottom.value = false
    }
  }

  function handleScroll() {
    // Scroll is the single source of truth: every input method (wheel,
    // scrollbar drag, trackpad, keyboard, programmatic) lands here.
    // Two-way sync: near bottom => follow; away => stop following.
    const el = elementRef.value
    const currentScrollTop = el ? normalizedScrollTop(el) : 0
    if (sentinelRef?.value) {
      const movedUp = currentScrollTop < lastScrollTop - 0.5
      const contentShrank = Boolean(el && el.scrollHeight < lastScrollHeight - 0.5)
      lastScrollTop = currentScrollTop
      lastScrollHeight = el?.scrollHeight ?? 0
      if (programmatic) programmatic = false
      // A bottom-directed programmatic scroll never moves upward. Therefore an
      // upward position change must win immediately even if a stale
      // programmatic marker is waiting to be consumed (for example, the user
      // grabs the scrollbar before the browser dispatches the write's event).
      if (movedUp && !contentShrank) {
        autoFollow.value = false
        atBottom.value = false
      } else if (sentinelVisible) {
        autoFollow.value = true
        atBottom.value = true
      }
      return
    }
    if (programmatic) {
      programmatic = false
      const near = isNearBottom()
      atBottom.value = near
      if (near) {
        autoFollow.value = true
        return
      }
      // A real user scroll can win the race after a scheduled write. Keyboard
      // and scrollbar input do not emit wheel, so judge the landed position
      // instead of blindly consuming the first scroll event.
    }
    const near = isNearBottom()
    autoFollow.value = near
    atBottom.value = near
  }

  function handleSentinelVisibility(visible: boolean) {
    sentinelVisible = visible
    atBottom.value = visible
    if (visible) autoFollow.value = true
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

    const sentinel = sentinelRef?.value
    if (sentinel) {
      const initialScrollHeight = el.scrollHeight
      programmatic = true
      sentinel.scrollIntoView({
        block: 'end',
        inline: 'nearest',
        behavior: effectiveSmooth ? 'smooth' : 'auto',
      })
      autoFollow.value = true
      atBottom.value = true
      await (options.afterFrame?.() ?? afterFrame())
      if (seq !== mySeq) return
      if (el.scrollHeight !== initialScrollHeight) {
        programmatic = true
        sentinel.scrollIntoView({ block: 'end', inline: 'nearest', behavior: 'auto' })
      }
      return
    }

    if (effectiveSmooth && typeof el.scrollTo === 'function') {
      const target = maxScrollTop(el)
      programmatic = true
      el.scrollTo({ top: target, behavior: 'smooth' })
      autoFollow.value = true
      atBottom.value = true
      return
    }

    const initialScrollHeight = el.scrollHeight
    programmatic = true
    el.scrollTop = maxScrollTop(el)
    // Correct only when content actually grew after the first write. Comparing
    // scrollTop with scrollHeight always requested a redundant second write,
    // because the browser's real bottom is scrollHeight-clientHeight.
    await (options.afterFrame?.() ?? afterFrame())
    if (seq !== mySeq) return
    if (el.scrollHeight !== initialScrollHeight) {
      programmatic = true
      el.scrollTop = maxScrollTop(el)
    }
    autoFollow.value = true
    atBottom.value = true
  }

  function reset() {
    // 易错点 8/18: discard any in-flight scroll, restore intent & position.
    seq++
    programmatic = false
    sentinelVisible = true
    lastScrollTop = elementRef.value ? normalizedScrollTop(elementRef.value) : 0
    lastScrollHeight = elementRef.value?.scrollHeight ?? 0
    autoFollow.value = true
    atBottom.value = true
  }

  // The controller owns the one canonical bottom-sentinel observer. Consumers
  // only render a sentinel and pass its ref; plugin chat surfaces therefore
  // cannot drift into a second observer implementation.
  let sentinelObserver: IntersectionObserver | null = null
  let observerGeneration = 0
  const stopSentinelWatch = sentinelRef
    ? watch([elementRef, sentinelRef], ([root, target]) => {
      const generation = ++observerGeneration
      sentinelObserver?.disconnect()
      sentinelObserver = null
      if (typeof IntersectionObserver === 'undefined' || !root || !target) return
      sentinelObserver = new IntersectionObserver((entries) => {
        if (generation !== observerGeneration
          || root !== elementRef.value
          || target !== sentinelRef.value) return
        const entry = entries.find(item => item.target === target)
        if (!entry) return
        const wasFollowing = autoFollow.value
        const visible = coreIsBottomSentinelVisible(entry)
        handleSentinelVisibility(visible)
        if (!visible && wasFollowing) void scrollToBottom()
      }, {
        root: root as Element,
        rootMargin: '0px',
        threshold: [0, CORE_SCROLL_SENTINEL_VISIBLE_RATIO],
      })
      sentinelObserver.observe(target as Element)
    }, { immediate: true, flush: 'post' })
    : undefined

  if (getCurrentScope()) {
    onScopeDispose(() => {
      observerGeneration++
      sentinelObserver?.disconnect()
      sentinelObserver = null
      stopSentinelWatch?.()
    })
  }

  return {
    autoFollow,
    atBottom,
    isNearBottom,
    handleWheel,
    handleScroll,
    handleSentinelVisibility,
    scrollToBottom,
    reset,
  }
}

function afterFrame(): Promise<void> {
  if (typeof requestAnimationFrame !== 'function') return Promise.resolve()
  return new Promise(resolve => requestAnimationFrame(() => resolve()))
}
