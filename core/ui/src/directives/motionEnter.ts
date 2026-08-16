/**
 * v-motion-enter — 挂载时的一次性入场动效（消息 / 会话条目等列表项用）
 *
 * 约束（对齐 perf 文档的动效红线）：
 * - mount-only：只在元素挂载时播一次，不写响应式状态、不动兄弟节点
 * - transform/opacity only：不触发布局，与 .message-view 的 contain/content-visibility 兼容
 * - gsap 只作用于局部元素，卸载时 killTweensOf 清理（镜像 v-beam 的局部化模式）
 * - binding.value === false（初始批次成员）跳过；prefers-reduced-motion 跳过
 */
import { gsap } from 'gsap'

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)')

export const motionEnterDirective = {
  mounted(el: HTMLElement, binding: { value?: unknown }) {
    if (binding.value === false) return
    if (REDUCED_MOTION.matches) return
    if (typeof requestAnimationFrame !== 'function') return
    gsap.fromTo(
      el,
      { autoAlpha: 0, y: 8 },
      {
        autoAlpha: 1,
        y: 0,
        duration: 0.22,
        ease: 'power2.out',
        overwrite: true,
        clearProps: 'autoAlpha,transform',
      },
    )
  },
  unmounted(el: HTMLElement) {
    gsap.killTweensOf(el)
  },
}
