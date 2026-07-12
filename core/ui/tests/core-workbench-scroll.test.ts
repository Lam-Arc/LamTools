import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { coreIsScrollNearBottom, useCoreAutoFollowScroll, type CoreScrollableElement } from '../src'

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

describe('core workbench auto-follow scroll', () => {
  it('detects whether the thread is near the bottom', () => {
    expect(coreIsScrollNearBottom({ scrollHeight: 1000, scrollTop: 620, clientHeight: 300 })).toBe(true)
    expect(coreIsScrollNearBottom({ scrollHeight: 1000, scrollTop: 500, clientHeight: 300 })).toBe(false)
    expect(coreIsScrollNearBottom(null)).toBe(true)
  })

  it('lets upward wheel input seize control and restores follow when user reaches bottom', () => {
    const el = fakeScrollElement()
    const controller = useCoreAutoFollowScroll(ref(el))

    expect(controller.autoFollow.value).toBe(true)
    controller.handleWheel({ deltaY: -1 })
    expect(controller.autoFollow.value).toBe(false)

    el.scrollTop = 500
    controller.handleScroll()
    expect(controller.autoFollow.value).toBe(false)

    el.scrollTop = 620
    controller.handleScroll()
    expect(controller.autoFollow.value).toBe(true)
  })

  it('scrolls only when following unless forced', async () => {
    const el = fakeScrollElement()
    const controller = useCoreAutoFollowScroll(ref(el), {
      afterDomUpdate: async () => {},
      afterFrame: async () => {},
      reduceMotion: () => false,
    })

    controller.handleWheel({ deltaY: -1 })
    await controller.scrollToBottom()
    expect(el.calls).toEqual([])

    await controller.scrollToBottom(true, 'smooth')
    expect(el.calls).toEqual([{ top: 1000, behavior: 'smooth' }])
    expect(controller.autoFollow.value).toBe(true)
  })

  it('falls back to direct scroll when reduced motion is requested', async () => {
    const el = fakeScrollElement()
    const controller = useCoreAutoFollowScroll(ref(el), {
      afterDomUpdate: async () => {},
      afterFrame: async () => {},
      reduceMotion: () => true,
    })

    await controller.scrollToBottom(true, 'smooth')
    expect(el.calls).toEqual([])
    expect(el.scrollTop).toBe(1000)
  })
})
