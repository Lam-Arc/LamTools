/**
 * presets — 全项目动效的唯一参数来源。
 *
 * user:“还有动画什么的可复用性，我打个比方，像是下载窗口弹出的那个动画，
 * 就是连贯且流畅，还有弹性的，这就是一个优秀的动画，让它可复用”+
 * (把入场、弹出、形变、展开、离场的时长与曲线收在一处；守卫与清理逻辑只写一遍，
 *  组件不再各自复制一份 shouldSkipMotion 与 clearProps)
 *
 * 约定：
 * - 只碰 transform 与 opacity，不写布局属性；
 * - 每次动画结束都 clearProps，避免内联样式残留；
 * - prefers-reduced-motion、无 window、无 rAF（jsdom）时退化为瞬时切换。
 */
import { gsap } from 'gsap'

export interface MorphVector {
  x: number
  y: number
  scaleX: number
  scaleY: number
}

/** 减弱动效或运行环境不支持时，调用方应直接切到终态。 */
export function shouldSkipMotion(): boolean {
  return (
    typeof window === 'undefined'
    || typeof window.matchMedia !== 'function'
    || window.matchMedia('(prefers-reduced-motion: reduce)').matches
    || typeof requestAnimationFrame !== 'function'
  )
}

export const MOTION = {
  /** 列表项、产出块：短距离上移淡入。 */
  fade: { duration: 0.22, y: 8, ease: 'power2.out' },
  /** 菜单、浮层：带一点过冲的弹出。 */
  pop: { duration: 0.32, y: 10, scale: 0.95, ease: 'back.out(1.2)' },
  /** 从触发点长出来的形变：过冲更明显，起点压到触发件大小。 */
  morph: { duration: 0.62, ease: 'back.out(1.2)', fromOpacity: 0.45 },
  /** 离场统一走加速曲线，比入场快。 */
  exit: { duration: 0.34, ease: 'power3.in', opacity: 0.3 },
  /** 折叠面板。 */
  expand: { duration: 0.24, ease: 'power2.out' },
  collapse: { duration: 0.2, ease: 'power2.in' },
  /** 遮罩淡入淡出。 */
  scrimIn: { duration: 0.26, ease: 'power1.out' },
  scrimOut: { duration: 0.3, ease: 'power2.in' },
  /** 减弱动效时保留的极短淡入。 */
  reduced: { duration: 0.22, ease: 'power2.out' },
} as const

/** 淡入上移，结束后清理内联样式。 */
export function enterFade(el: Element, done?: () => void): void {
  if (shouldSkipMotion()) {
    done?.()
    return
  }
  gsap.fromTo(
    el,
    { autoAlpha: 0, y: MOTION.fade.y },
    {
      autoAlpha: 1,
      y: 0,
      duration: MOTION.fade.duration,
      ease: MOTION.fade.ease,
      overwrite: true,
      clearProps: 'autoAlpha,transform',
      onComplete: () => done?.(),
    },
  )
}

/** 遮罩淡入。 */
export function enterScrim(el: Element | null): void {
  if (!el || shouldSkipMotion()) return
  gsap.fromTo(
    el,
    { autoAlpha: 0 },
    { autoAlpha: 1, duration: MOTION.scrimIn.duration, ease: MOTION.scrimIn.ease },
  )
}

/** 遮罩淡出。 */
export function leaveScrim(el: Element | null): void {
  if (!el || shouldSkipMotion()) return
  gsap.to(el, { autoAlpha: 0, duration: MOTION.scrimOut.duration, ease: MOTION.scrimOut.ease })
}

/**
 * 目标元素相对触发点的位移与缩放。
 * 缩放下限 0.06：触发件很小时也不会把卡片压成零尺寸。
 */
export function morphFrom(origin: HTMLElement, target: HTMLElement): MorphVector {
  const from = origin.getBoundingClientRect()
  const to = target.getBoundingClientRect()
  return {
    x: from.left + from.width / 2 - (to.left + to.width / 2),
    y: from.top + from.height / 2 - (to.top + to.height / 2),
    scaleX: Math.max(0.06, from.width / to.width),
    scaleY: Math.max(0.06, from.height / to.height),
  }
}

/** 从触发点长出来：先压回触发件大小，再用过冲长到自身尺寸。 */
export function enterMorph(el: Element | null, origin: HTMLElement | null): void {
  if (!el || !origin || shouldSkipMotion()) return
  const start = morphFrom(origin, el as HTMLElement)
  gsap.set(el, { ...start, autoAlpha: MOTION.morph.fromOpacity, transformOrigin: '50% 50%' })
  gsap.to(el, {
    x: 0,
    y: 0,
    scaleX: 1,
    scaleY: 1,
    autoAlpha: 1,
    duration: MOTION.morph.duration,
    ease: MOTION.morph.ease,
    clearProps: 'transformOrigin',
  })
}

/** 原路缩回触发点，返回的 Promise 在动画结束时兑现。 */
export function leaveMorph(el: Element | null, origin: HTMLElement | null): Promise<void> {
  if (!el || !origin || shouldSkipMotion()) return Promise.resolve()
  const end = morphFrom(origin, el as HTMLElement)
  return new Promise<void>((resolve) => {
    gsap.to(el, {
      ...end,
      autoAlpha: MOTION.exit.opacity,
      duration: MOTION.exit.duration,
      ease: MOTION.exit.ease,
      onComplete: resolve,
    })
  })
}
