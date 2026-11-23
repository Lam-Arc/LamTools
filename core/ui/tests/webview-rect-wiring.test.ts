import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'
import { WORKSPACE_AREA_RECT } from '../src/components/workspaceInjection'
import { openOverlay, resetBrowserOverlays } from '../src/split/browserOverlays'
import { defineComponent, h, provide } from 'vue'

/**
 * user:“把浏览器面板的矩形收到引擎算出的 contentRect”+(V2-C1b：
 * 下发的物理矩形**只能**来自注入的 contentRect；把 `getBoundingClientRect()` 桩成
 * 完全不同的值，断言它没被使用。)
 */
const contentRect: Rect = { x: 100, y: 200, width: 400, height: 300 }
const hostRect: Rect = { x: 90, y: 150, width: 500, height: 400 }

const wrappers: Array<ReturnType<typeof mount>> = []
const originalDpr = Object.getOwnPropertyDescriptor(window, 'devicePixelRatio')
const originalGbc = Element.prototype.getBoundingClientRect

beforeEach(() => {
  // dpr 固定 2：物理值一眼可辨（contentRect × 2）。
  Object.defineProperty(window, 'devicePixelRatio', { configurable: true, get: () => 2 })
  // DOM 测量一律给离谱值：只要它被用到，断言立刻炸。
  Element.prototype.getBoundingClientRect = function stub() {
    return { x: 9999, y: 9999, width: 8888, height: 7777, top: 9999, left: 9999, right: 1, bottom: 1, toJSON() { return {} } } as DOMRect
  }
})

afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  resetBrowserOverlays()
  Element.prototype.getBoundingClientRect = originalGbc
  if (originalDpr) Object.defineProperty(window, 'devicePixelRatio', originalDpr)
})

function mountBrowser(options: {
  content?: Rect
  host?: Rect
  phase?: string
  visible?: boolean
} = {}) {
  const calls: Array<{ action: string; options?: Record<string, unknown> }> = []
  const services = {
    available: () => true,
    call: vi.fn(async (_id: string, action: string, opts?: Record<string, unknown>) => {
      calls.push({ action, options: opts })
      if (action === 'create') return { tab: 't1' }
      if (action === 'state') return {}
      return undefined
    }),
    subscribe: vi.fn(async () => () => {}),
    openExternal: vi.fn(async () => {}),
  }
  const areaRects = () => ({ contentRect: options.content ?? contentRect, hostRect: options.host ?? hostRect })
  const browserProps = {
    tab: { id: 'area-1', kind: 'browser', resource: 'https://example.com', title: 'Example' },
    visible: options.visible ?? true,
    services,
    pane: 'area-1',
    controller: options.phase ? { interactionPhase: { value: options.phase } } : undefined,
  }
  // user:“provide 用 Symbol 键”+(`global.provide` 只遍历字符串键，Symbol 会丢；
  //  所以包一层壳组件，在 setup 里真正 provide 一次，再渲染被测组件。)
  const Host = defineComponent({
    setup(_props, { slots }) {
      provide(WORKSPACE_AREA_RECT, areaRects)
      return () => slots.default?.()
    },
  })
  const wrapper = mount(Host, {
    slots: { default: () => h(CoreSplitBrowser, browserProps as never) },
  })
  wrappers.push(wrapper)
  const lastBounds = () => [...calls].reverse().find(call => call.action === 'bounds')
  return { wrapper, calls, lastBounds }
}

describe('webview rect wiring (contentRect → physical args)', () => {
  it('下发的物理矩形只来自 contentRect，且等于 round(css × dpr)', async () => {
    const { lastBounds } = mountBrowser()
    await new Promise(resolve => setTimeout(resolve, 50))
    const bounds = lastBounds()
    expect(bounds, '应至少下发一次 bounds').toBeTruthy()
    expect(bounds?.options).toMatchObject({ x: 200, y: 400, width: 800, height: 600 })
    // 桩值 9999×8888 一旦被用到，这里就会变成 19998 —— 断言它没被使用。
    expect(bounds?.options?.x).not.toBe(19998)
  })

  it('overlayDepth() > 0 → visible:false', async () => {
    const release = openOverlay('menu')
    const { lastBounds } = mountBrowser()
    await new Promise(resolve => setTimeout(resolve, 50))
    expect(lastBounds()?.options?.visible).toBe(false)
    release()
  })

  it('phase=floating（浮层拖动）→ 保持 visible:true', async () => {
    const { lastBounds } = mountBrowser({ phase: 'floating' })
    await new Promise(resolve => setTimeout(resolve, 50))
    expect(lastBounds()?.options?.visible).toBe(true)
  })

  it('contentRect 超出区域 → 下发求交结果', async () => {
    const overflowing: Rect = { x: 400, y: 300, width: 400, height: 400 }
    const { lastBounds } = mountBrowser({ content: overflowing })
    await new Promise(resolve => setTimeout(resolve, 50))
    // host = (90,150,500,400) → 交集 x 400..590 → 宽 190；y 300..550 → 高 250。
    expect(lastBounds()?.options).toMatchObject({ x: 800, y: 600, width: 380, height: 500 })
  })

  it('contentRect 面积为 0 → visible:false', async () => {
    const { lastBounds } = mountBrowser({ content: { x: 100, y: 200, width: 0, height: 0 } })
    await new Promise(resolve => setTimeout(resolve, 50))
    const bounds = lastBounds()
    if (bounds) expect(bounds.options?.visible).toBe(false)
  })
})
