/**
 * fadeSlide — 轻量淡入/滑入的 GSAP 过渡钩子（Vue <Transition :css="false"> 用）
 *
 * user:“合并去重”+(原来这里的 shouldSkipMotion 与 motionEnter 指令各写一份，
 *  现在守卫与参数都在 motion/presets.ts，本文件只保留 Vue 过渡钩子的形状)
 *
 * - 入场：预设 enterFade，autoAlpha 0→1 + y 8→0，结束后 clearProps 还原内联样式
 * - 离场：瞬时直切（这里只用于「出现类」元素，移除时无需离场动画）
 * - prefers-reduced-motion / 无 rAF 环境（jsdom 测试）直接 done()
 */
import { enterFade } from './presets.ts'

export function fadeSlideEnter(el: Element, done: () => void): void {
  enterFade(el, done)
}

export function fadeSlideLeave(el: Element, done: () => void): void {
  done()
}
