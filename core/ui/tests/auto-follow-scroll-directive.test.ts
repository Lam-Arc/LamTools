import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { autoFollowScrollDirective } from '../src/directives/autoFollowScroll'

/**
 * 指令级（v-auto-follow-scroll）契约测试 —— 覆盖易错点 5/6/9/10/12/13/16/17。
 *
 * jsdom 没有真实布局 / ResizeObserver；这里：
 *  - 用可控的假 ResizeObserver 模拟内容增长触发；
 *  - 给元素 defineProperty 挂可变 scrollHeight / scrollTop / clientHeight。
 */

interface FakeRO {
  instances: Array<{ observer: ResizeObserver; targets: Set<Element>; callback: ResizeObserverCallback }>
  last: () => { observer: ResizeObserver; targets: Set<Element>; callback: ResizeObserverCallback } | undefined
  fire: (entry: Element) => void
  restore: () => void
}

function installFakeResizeObserver(): FakeRO {
  const instances: FakeRO['instances'] = []
  const original = (globalThis as unknown as { ResizeObserver?: unknown }).ResizeObserver

  class FakeROImpl {
    callback: ResizeObserverCallback
    targets = new Set<Element>()
    constructor(callback: ResizeObserverCallback) {
      this.callback = callback
      instances.push({ observer: this as unknown as ResizeObserver, targets: this.targets, callback })
    }
    observe(target: Element) { this.targets.add(target) }
    unobserve(target: Element) { this.targets.delete(target) }
    disconnect() { this.targets.clear() }
  }

  ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = FakeROImpl

  return {
    instances,
    last: () => instances[instances.length - 1],
    fire: (entry: Element) => {
      const inst = instances[instances.length - 1]
      if (!inst) return
      inst.callback([{ target: entry } as ResizeObserverEntry], inst.observer)
    },
    restore: () => {
      if (original !== undefined) {
        ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = original as never
      } else {
        delete (globalThis as unknown as { ResizeObserver?: unknown }).ResizeObserver
      }
    },
  }
}

/** 可滚动元素：带可变 scrollHeight，且 scrollTop 设置会派发真实 scroll 事件（仿真浏览器） */
function makeScrollable(scrollHeight = 1000, clientHeight = 300): HTMLElement & {
  __setHeight: (h: number) => void
  __setTop: (t: number) => void
} {
  const el = document.createElement('div')
  el.style.overflowY = 'auto'
  let h = scrollHeight
  let t = 0
  Object.defineProperty(el, 'scrollHeight', {
    configurable: true,
    get: () => h,
  })
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: clientHeight })
  Object.defineProperty(el, 'scrollTop', {
    configurable: true,
    get: () => t,
    set(v) {
      t = v
      el.dispatchEvent(new Event('scroll'))
    },
  })
  return Object.assign(el, {
    __setHeight: (next: number) => { h = next },
    __setTop: (next: number) => { t = next; el.dispatchEvent(new Event('scroll')) },
  })
}

function mount(el: HTMLElement) {
  document.body.appendChild(el)
  autoFollowScrollDirective.mounted?.(el, { value: 'x', oldValue: '', modifiers: {}, arg: '' } as never, null as never, null as never)
}

function unmount(el: HTMLElement) {
  autoFollowScrollDirective.unmounted?.(el, {} as never, null as never, null as never)
  document.body.removeChild(el)
}

describe('v-auto-follow-scroll directive', () => {
  let fakeRO: FakeRO
  const attached: HTMLElement[] = []

  beforeEach(() => {
    fakeRO = installFakeResizeObserver()
  })

  afterEach(() => {
    for (const el of attached.splice(0)) unmount(el)
    fakeRO.restore()
    vi.restoreAllMocks()
  })

  it('scrolls to bottom on mount (initial content present)', async () => {
    const el = makeScrollable()
    attached.push(el)
    mount(el)
    await nextTick()
    // mount 首滚直接写 scrollTop = scrollHeight
    expect((el as unknown as { scrollTop: number }).scrollTop).toBe(1000)
  })

  it('follows content growth driven by ResizeObserver while user is at bottom', async () => {
    const el = makeScrollable(1000, 300)
    attached.push(el)
    mount(el)
    await nextTick()
    expect(el.scrollTop).toBe(1000)

    // Content grows: a direct child's box changes → RO fires for the child.
    const child = document.createElement('div')
    el.appendChild(child)
    el.__setHeight(2000)
    fakeRO.fire(child)
    await nextTick()

    expect(el.scrollTop).toBe(2000)
  })

  it('does not yank the user back after upward wheel + scroll away', async () => {
    const el = makeScrollable(1000, 300)
    attached.push(el)
    mount(el)
    await nextTick()
    expect(el.scrollTop).toBe(1000)

    // User scrolls up (wheel-first seizure, then the scroll event lands).
    el.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, bubbles: true }))
    // scrollTop setter fires the real scroll event synchronously
    el.__setTop(500)
    await nextTick()
    expect(el.scrollTop).toBe(500)

    // Content grows while the user is reading above.
    el.__setHeight(1500)
    fakeRO.fire(el)
    await nextTick()

    // Must not be yanked back to bottom.
    expect(el.scrollTop).toBe(500)

    // User returns near the bottom → follow re-enables on next growth.
    // near-bottom threshold: 1600-300-80 = 1220; scrollTop 1250 is inside.
    el.__setTop(1250)
    el.__setHeight(1600)
    fakeRO.fire(el)
    await nextTick()
    expect(el.scrollTop).toBe(1600)
  })

  it('resolves the nearest scrollable ancestor when the bound element is not scrollable', async () => {
    const outer = makeScrollable()
    outer.style.overflowY = 'auto'
    const inner = document.createElement('div')
    inner.style.overflow = 'visible'
    outer.appendChild(inner)
    document.body.appendChild(outer)
    attached.push(outer)

    autoFollowScrollDirective.mounted?.(inner, { value: 'x', oldValue: '', modifiers: {}, arg: '' } as never, null as never, null as never)
    await nextTick()

    // Target resolved to outer (nearest scrollable ancestor) — outer scrolled.
    expect(outer.scrollTop).toBe(1000)
  })

  it('observes late-mounted direct children (v-if content) and follows their growth', async () => {
    const el = makeScrollable()
    document.body.appendChild(el)
    attached.push(el)
    autoFollowScrollDirective.mounted?.(el, { value: 'x', oldValue: '', modifiers: {}, arg: '' } as never, null as never, null as never)
    await nextTick()

    const inst = fakeRO.last()!
    expect(inst.targets.has(el)).toBe(true)

    // A child mounts after the directive (v-if branch) — should be observed.
    const child = document.createElement('div')
    el.appendChild(child)
    // 模拟 Vue updated 钩子补 observe
    autoFollowScrollDirective.updated?.(el, { value: 'x', oldValue: 'x', modifiers: {}, arg: '' } as never, null as never, null as never)
    expect(inst.targets.has(child)).toBe(true)

    // Child growth triggers follow.
    el.__setHeight(1200)
    fakeRO.fire(child)
    await nextTick()
    expect(el.scrollTop).toBe(1200)
  })

  it('does not scroll on every updated when binding value unchanged (易错点 13)', async () => {
    const el = makeScrollable()
    attached.push(el)
    mount(el)
    await nextTick()
    const settled = el.scrollTop

    // 绑定值不变：updated 不滚（仅补 observe），避免逐帧滚动。
    autoFollowScrollDirective.updated?.(el, { value: 'x', oldValue: 'x', modifiers: {}, arg: '' } as never, null as never, null as never)
    await nextTick()
    // 没有 RO 触发、没有绑定值变化 → scrollTop 不应被再次修改
    expect(el.scrollTop).toBe(settled)
  })

  it('scrolls once when binding value actually changes (内容变了但尺寸未变的兜底)', async () => {
    const el = makeScrollable(1000, 300)
    attached.push(el)
    mount(el)
    await nextTick()
    expect(el.scrollTop).toBe(1000)

    autoFollowScrollDirective.updated?.(el, { value: 'y', oldValue: 'x', modifiers: {}, arg: '' } as never, null as never, null as never)
    await nextTick()
    expect(el.scrollTop).toBe(1000) // target 已达底，无需移动
  })

  it('cleans up listeners and observer on unmount', async () => {
    const el = makeScrollable()
    document.body.appendChild(el)
    autoFollowScrollDirective.mounted?.(el, { value: 'x', oldValue: '', modifiers: {}, arg: '' } as never, null as never, null as never)
    await nextTick()

    const inst = fakeRO.last()!
    const scrollSpy = vi.spyOn(el, 'removeEventListener')

    autoFollowScrollDirective.unmounted?.(el, {} as never, null as never, null as never)
    expect(inst.targets.size).toBe(0)
    expect(scrollSpy).toHaveBeenCalledWith('scroll', expect.any(Function))
    expect(scrollSpy).toHaveBeenCalledWith('wheel', expect.any(Function))
  })
})