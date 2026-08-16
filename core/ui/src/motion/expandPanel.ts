/**
 * expandPanel — 折叠/展开面板的 GSAP 过渡钩子（Vue <Transition :css="false"> 用）
 *
 * 替代曾经休眠的 CSS max-height 过渡（v-if 直切导致其从未生效）：
 * - 展开：height 0 → scrollHeight（受 max-height 钳制）+ 淡入，结束后 clearProps 还原自然高度
 * - 折叠：当前高度 → 0 + 淡出，Transition 在 leave 完成后移除 DOM（不保留大输出节点）
 * - 动画期间禁用元素自身的 CSS transition（opacity 会被 CSS 过渡二次插值造成拖影）
 * - prefers-reduced-motion / 无 rAF 环境（jsdom 测试）直接 done()，行为退化为瞬时切换
 */
import { gsap } from 'gsap'

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)')

const DURATION_OPEN = 0.24
const DURATION_CLOSE = 0.2

interface PanelMetrics {
  maxHeight: number | null
  paddingTop: number
  paddingBottom: number
  marginTop: number
  marginBottom: number
  transition: string
  overflow: string
}

function readMetrics(el: HTMLElement): PanelMetrics {
  const st = window.getComputedStyle(el)
  const max = parseFloat(st.maxHeight)
  return {
    maxHeight: Number.isFinite(max) && max > 0 ? max : null,
    paddingTop: parseFloat(st.paddingTop) || 0,
    paddingBottom: parseFloat(st.paddingBottom) || 0,
    marginTop: parseFloat(st.marginTop) || 0,
    marginBottom: parseFloat(st.marginBottom) || 0,
    transition: st.transition,
    overflow: st.overflow,
  }
}

function clampHeight(el: HTMLElement, metrics: PanelMetrics): number {
  const target = el.scrollHeight
  return metrics.maxHeight !== null ? Math.min(target, metrics.maxHeight) : target
}

function prepare(el: HTMLElement, metrics: PanelMetrics) {
  // 动画期间禁用 CSS transition，避免 GSAP 每帧的 opacity/height 写入被二次插值
  el.style.transition = 'none'
  el.style.overflow = 'hidden'
}

function restore(el: HTMLElement, metrics: PanelMetrics) {
  el.style.transition = metrics.transition === 'none' ? '' : metrics.transition
  el.style.overflow = metrics.overflow
  el.style.height = ''
  el.style.paddingTop = ''
  el.style.paddingBottom = ''
  el.style.marginTop = ''
  el.style.marginBottom = ''
  el.style.opacity = ''
}

export function panelEnter(el: Element, done: () => void) {
  const target = el as HTMLElement
  if (REDUCED_MOTION.matches || typeof requestAnimationFrame !== 'function') {
    done()
    return
  }
  const m = readMetrics(target)
  const height = clampHeight(target, m)
  prepare(target, m)
  gsap.fromTo(
    target,
    { height: 0, opacity: 0, paddingTop: 0, paddingBottom: 0, marginTop: 0, marginBottom: 0 },
    {
      height,
      opacity: 1,
      paddingTop: m.paddingTop,
      paddingBottom: m.paddingBottom,
      marginTop: m.marginTop,
      marginBottom: m.marginBottom,
      duration: DURATION_OPEN,
      ease: 'power2.out',
      overwrite: true,
      onComplete: () => {
        restore(target, m)
        done()
      },
    },
  )
}

export function panelLeave(el: Element, done: () => void) {
  const target = el as HTMLElement
  if (REDUCED_MOTION.matches || typeof requestAnimationFrame !== 'function') {
    done()
    return
  }
  const m = readMetrics(target)
  prepare(target, m)
  gsap.to(target, {
    height: 0,
    opacity: 0,
    paddingTop: 0,
    paddingBottom: 0,
    marginTop: 0,
    marginBottom: 0,
    duration: DURATION_CLOSE,
    ease: 'power2.in',
    overwrite: true,
    onComplete: () => {
      restore(target, m)
      done()
    },
  })
}
