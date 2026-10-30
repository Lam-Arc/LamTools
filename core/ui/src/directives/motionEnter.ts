/**
 * v-motion-enter — 挂载时的一次性入场动效（消息 / 会话条目等列表项用）
 *
 * user:“合并去重”+(与 motion/fadeSlide 同一套参数，统一走 presets 的 enterFade，
 *  不再各存一份 0.22 秒 / y 8 / power2.out 的副本)
 *
 * 约束（对齐 perf 文档的动效红线）：
 * - mount-only：只在元素挂载时播一次，不写响应式状态、不动兄弟节点
 * - transform/opacity only：不触发布局，与 .message-view 的 contain/content-visibility 兼容
 * - gsap 只作用于局部元素，卸载时 killTweensOf 清理
 * - binding.value === false（初始批次成员）跳过；prefers-reduced-motion 跳过
 */
import { gsap } from 'gsap'
import { enterFade, shouldSkipMotion } from '@/motion/presets.ts'

export const motionEnterDirective = {
  mounted(el: HTMLElement, binding: { value?: unknown }) {
    if (binding.value === false) return
    if (shouldSkipMotion()) return
    enterFade(el)
  },
  unmounted(el: HTMLElement) {
    gsap.killTweensOf(el)
  },
}
