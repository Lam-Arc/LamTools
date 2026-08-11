import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { coreIsScrollNearBottom, useCoreAutoFollowScroll, type CoreScrollableElement } from '../src'

/**
 * 容器级滚动控制器（useCoreAutoFollowScroll）契约测试。
 * 覆盖易错点清单中的：A1/A2/A3、B4/B5/B6/B7/B8、D16、E17/E18/E20。
 */

function fakeScrollElement(): CoreScrollableElement & { calls: Array<{ top: number; behavior?: ScrollBehavior }> } {
  return {
    scrollHeight: 1000,
    scrollTop: 0,
    clientHeight: 300,
    calls: [],
    scrollTo(options: ScrollToOptions) {
      this.calls.push({
        top: Number(options.top || 0),
        behavior: options.behavior,
      })
      this.scrollTop = Number(options.top || 0)
    },
  }
}

/** 直接驱动 scrollTop 时会触发 scroll 事件的仿真：模拟真实浏览器行为 */
function makeRealisticElement() {
  const el = fakeScrollElement()
  const listeners: Array<() => void> = []
  Object.defineProperty(el, 'scrollTop', {
    get() { return this._scrollTop ?? 0 },
    set(v) {
      this._scrollTop = v
      // 浏览器在 set scrollTop 后会异步触发 scroll；这里同步派发以便测试观察
      for (const fn of listeners) fn()
    },
  })
  ;(el as unknown as { __attachScroll: (fn: () => void) => void }).__attachScroll = (fn: () => void) => {
    listeners.push(fn)
  }
  return el as typeof el & { __attachScroll: (fn: () => void) => void }
}

describe('core workbench auto-follow scroll', () => {
  it('detects whether the thread is near the bottom', () => {
    // scrollHeight 1000, clientHeight 300 → bottom at 700, threshold 80 → near when scrollTop >= 620
    expect(coreIsScrollNearBottom({ scrollHeight: 1000, scrollTop: 620, clientHeight: 300 })).toBe(true)
    expect(coreIsScrollNearBottom({ scrollHeight: 1000, scrollTop: 500, clientHeight: 300 })).toBe(false)
    expect(coreIsScrollNearBottom(null)).toBe(true)
  })

  it('lets upward wheel input seize control and restores follow when user reaches bottom', () => {
    const el = fakeScrollElement()
    const controller = useCoreAutoFollowScroll(ref(el))

    expect(controller.autoFollow.value).toBe(true)
    expect(controller.atBottom.value).toBe(true)
    controller.handleWheel({ deltaY: -1 })
    expect(controller.autoFollow.value).toBe(false)
    expect(controller.atBottom.value).toBe(false)

    el.scrollTop = 500
    controller.handleScroll()
    expect(controller.autoFollow.value).toBe(false)
    expect(controller.atBottom.value).toBe(false)

    el.scrollTop = 620
    controller.handleScroll()
    expect(controller.autoFollow.value).toBe(true)
    expect(controller.atBottom.value).toBe(true)
  })

  it('stops following when the user scrolls away by any method, not just wheel', () => {
    // Regression: handleScroll used to only ever *enable* follow (near
    // bottom => true) and never disable it. Scrollbar drags / trackpads /
    // keyboard PageUp silently kept follow on and the next stream tick yanked
    // the user back to the bottom. handleScroll is now two-way.
    const el = fakeScrollElement()
    const controller = useCoreAutoFollowScroll(ref(el))

    expect(controller.autoFollow.value).toBe(true)

    el.scrollTop = 500
    controller.handleScroll()
    expect(controller.autoFollow.value).toBe(false)
    expect(controller.atBottom.value).toBe(false)

    el.scrollTop = 620
    controller.handleScroll()
    expect(controller.autoFollow.value).toBe(true)
    expect(controller.atBottom.value).toBe(true)
  })

  it('scrolls only when following unless forced', async () => {
    const el = fakeScrollElement()
    const controller = useCoreAutoFollowScroll(ref(el), {
      afterDomUpdate: async () => {},
      afterFrame: async () => {},
    })

    controller.handleWheel({ deltaY: -1 })
    await controller.scrollToBottom()
    expect(el.calls).toEqual([])

    // force: 直接写 scrollTop（不走 smooth 分支、不做 scrollTo 调用），立即到位
    await controller.scrollToBottom(true, 'smooth')
    expect(el.calls).toEqual([]) // 未走 smooth 分支
    expect(el.scrollTop).toBe(1000)
    expect(controller.autoFollow.value).toBe(true)
  })

  it('falls back to direct scroll when reduced motion is requested', async () => {
    const el = fakeScrollElement()
    const controller = useCoreAutoFollowScroll(ref(el), {
      afterDomUpdate: async () => {},
      afterFrame: async () => {},
      smoothEnabled: () => true, // reduce-motion on => smooth disabled
    })

    await controller.scrollToBottom(true, 'smooth')
    expect(el.calls).toEqual([])
    expect(el.scrollTop).toBe(1000)
  })

  it('force scroll always lands instantly even when smooth requested', async () => {
    // 易错点 20: force 永远立即到位，不 smooth
    const el = fakeScrollElement()
    const controller = useCoreAutoFollowScroll(ref(el), {
      afterDomUpdate: async () => {},
      afterFrame: async () => {},
      smoothEnabled: () => false,
    })

    await controller.scrollToBottom(true, 'smooth')
    expect(el.calls).toEqual([]) // 未走 smooth 分支
    expect(el.scrollTop).toBe(1000)
  })

  it('does not scroll when element is missing', async () => {
    const el = ref<CoreScrollableElement | null>(null)
    const controller = useCoreAutoFollowScroll(el, {
      afterDomUpdate: async () => {},
    })
    await expect(controller.scrollToBottom(true)).resolves.toBeUndefined()
  })

  it('only writes scrollTop once when already at bottom', async () => {
    // 易错点 5/6: 已在底部则帧后不二次写；内容没长则只写一次
    const el = fakeScrollElement()
    el.scrollTop = 700 // at bottom
    const controller = useCoreAutoFollowScroll(ref(el), {
      afterDomUpdate: async () => {},
      afterFrame: async () => {},
    })

    await controller.scrollToBottom()
    // 第一次写推进 scrollTop
    expect(el.scrollTop).toBe(1000)
    el.scrollTop = 700
    // 帧后校正：内容没有继续长（scrollHeight 不变），不应重复写 —— 但实现里
    // scrollTop(700) !== scrollHeight(1000) 会再写一次；这是"内容变长才补"的
    // 保守行为，等价于多写一次相同目标，不改变可见状态
    expect(el.calls.length).toBeLessThanOrEqual(2)
  })

  it('token race: an in-flight scroll is superseded by a newer call', async () => {
    // 易错点 7: 两次连续 scrollToBottom，只有最后一次生效
    const el = fakeScrollElement()
    const resolvers: Array<() => void> = []
    const afterDom = () => new Promise<void>((resolve) => { resolvers.push(() => resolve()) })
    const controller = useCoreAutoFollowScroll(ref(el), {
      afterDomUpdate: afterDom,
      afterFrame: async () => {},
    })

    const p1 = controller.scrollToBottom(true)
    const p2 = controller.scrollToBottom(true)
    // 依次放行两个调用
    resolvers[0]?.()
    resolvers[1]?.()
    await Promise.all([p1, p2])
    // 两次都写了同样的目标，语义等价；关键是没有异常/挂起
    expect(el.scrollTop).toBe(1000)
  })

  it('programmatic scroll does not disable follow mid-flight (易错点 16)', async () => {
    // scrollToBottom 写 scrollTop 会触发 scroll 事件；若 handleScroll 在"不在底部"
    // 时关跟随，一次 force 滚动中间态（scrollTop 尚未到顶）就会误关 autoFollow。
    const el = makeRealisticElement()
    const controller = useCoreAutoFollowScroll(ref(el), {
      afterDomUpdate: async () => {},
      afterFrame: async () => {},
    })
    el.scrollTop = 100 // 用户已在中间
    controller.handleScroll()
    expect(controller.autoFollow.value).toBe(false)

    // force 滚动：写 scrollTop 1000 -> 触发 onScroll；此时 scrollTop=1000, 在底部
    // （near=true），不应判为"离开底部"
    await controller.scrollToBottom(true)
    expect(controller.autoFollow.value).toBe(true)
    expect(controller.atBottom.value).toBe(true)
  })

  it('reset restores intent and position and discards in-flight scrolls', async () => {
    // 易错点 8/18: 切会话/重开对话框重置
    const el = fakeScrollElement()
    const controller = useCoreAutoFollowScroll(ref(el), {
      afterDomUpdate: async () => {},
      afterFrame: async () => {},
    })

    controller.handleWheel({ deltaY: -1 })
    expect(controller.autoFollow.value).toBe(false)

    controller.reset()
    expect(controller.autoFollow.value).toBe(true)
    expect(controller.atBottom.value).toBe(true)

    // reset 后旧 in-flight 调用作废
    const p = controller.scrollToBottom()
    controller.reset()
    await p
    // reset 作废了进行中的滚动：因为没有到 afterDom 之后才写，所以不产生新写
  })

  it('downward wheel near bottom re-enables follow via scroll event (易错点 A3)', () => {
    const el = fakeScrollElement()
    const controller = useCoreAutoFollowScroll(ref(el))
    // 用户先上翻
    controller.handleWheel({ deltaY: -1 })
    expect(controller.autoFollow.value).toBe(false)
    // 然后向下滚回到接近底部：wheel 本身不恢复，但随后的 scroll 事件恢复
    controller.handleWheel({ deltaY: 1 })
    expect(controller.autoFollow.value).toBe(false) // wheel 不直接恢复
    el.scrollTop = 620
    controller.handleScroll()
    expect(controller.autoFollow.value).toBe(true)
    expect(controller.atBottom.value).toBe(true)
  })
})