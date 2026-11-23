import type { ObjectDirective } from 'vue'
import { shouldSkipMotion } from '../motion/presets.ts'

type ReorderItems = readonly { id: string }[]
type Position = { x: number; y: number }

const previousPositions = new WeakMap<HTMLElement, Map<HTMLElement, Position>>()
const activeAnimations = new WeakMap<HTMLElement, Map<HTMLElement, Animation>>()

function measure(list: HTMLElement, only?: Map<HTMLElement, Position>): Map<HTMLElement, Position> {
  const origin = list.getBoundingClientRect()
  const positions = new Map<HTMLElement, Position>()
  for (const child of list.children) {
    if (!(child instanceof HTMLElement) || (only && !only.has(child))) continue
    const rect = child.getBoundingClientRect()
    if (rect.width && rect.height) positions.set(child, { x: rect.left - origin.left, y: rect.top - origin.top })
  }
  return positions
}

function stopAnimations(list: HTMLElement): void {
  for (const animation of activeAnimations.get(list)?.values() ?? []) animation.cancel()
  activeAnimations.delete(list)
}

// user:“再track目前最大卡顿因素是什么，然后修复”+
// (固定身份顺序的状态刷新不测量布局，真正换序时保留侧栏滑动)。
export const reorderMotionDirective: ObjectDirective<HTMLElement, ReorderItems> = {
  beforeUpdate(list, { value, oldValue }) {
    if (!oldValue || (oldValue.length === value.length && oldValue.every((item, i) => item.id === value[i].id))) return
    if (oldValue.length && value.length && !shouldSkipMotion()) previousPositions.set(list, measure(list))
    stopAnimations(list)
  },
  updated(list) {
    const before = previousPositions.get(list)
    if (!before) return
    previousPositions.delete(list)
    if (!before.size) return

    const style = getComputedStyle(list)
    const token = style.getPropertyValue('--dur-base').trim()
    const duration = Number.parseFloat(token) * (token.endsWith('ms') ? 1 : 1000)
    if (!Number.isFinite(duration) || duration <= 0) return
    const easing = style.getPropertyValue('--ease-out').trim() || 'ease-out'

    const after = measure(list, before)
    const running = new Map<HTMLElement, Animation>()
    for (const [child, to] of after) {
      const from = before.get(child)!
      const x = from.x - to.x
      const y = from.y - to.y
      if ((!x && !y) || typeof child.animate !== 'function') continue
      const animation = child.animate([{ translate: `${x}px ${y}px` }, { translate: '0px 0px' }], { duration, easing })
      running.set(child, animation)
      animation.onfinish = () => running.delete(child)
    }
    if (running.size) activeAnimations.set(list, running)
  },
  beforeUnmount(list) {
    previousPositions.delete(list)
    stopAnimations(list)
  },
}
