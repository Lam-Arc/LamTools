/**
 * fadeSlide — 轻量淡入/滑入的 GSAP 过渡钩子（Vue <Transition :css="false"> 用）
 *
 * - 入场：autoAlpha 0→1 + y 8→0（transform 别名 + autoAlpha，不碰布局属性；
 *   clearProps 在动画结束时还原内联样式）
 * - 离场：瞬时直切（这里只用于「出现类」元素——本轮产出面板、决策答复等，
 *   移除时无需离场动画）
 * - prefers-reduced-motion / 无 rAF 环境（jsdom 测试）直接 done()，行为退化为瞬时切换
 */
import { gsap } from 'gsap'

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)')

const DURATION_ENTER = 0.22

export function fadeSlideEnter(el: Element, done: () => void): void {
  if (REDUCED_MOTION.matches || typeof requestAnimationFrame !== 'function') {
    done()
    return
  }
  gsap.fromTo(
    el,
    { autoAlpha: 0, y: 8 },
    {
      autoAlpha: 1,
      y: 0,
      duration: DURATION_ENTER,
      ease: 'power2.out',
      overwrite: true,
      clearProps: 'autoAlpha,transform',
      onComplete: () => done(),
    },
  )
}

export function fadeSlideLeave(el: Element, done: () => void): void {
  done()
}
