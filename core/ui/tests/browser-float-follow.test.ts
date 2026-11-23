import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })

function mountFloat() {
  const calls: Array<{ action: string; options?: Record<string, unknown> }> = []
  // 浮窗矩形由组件写在 tab 上；这里让宿主 rect 跟着矩形联动，模拟“外框动 → 网页宿主也动”。
  const tab = reactive({
    id: 't1', kind: 'browser' as const, title: '示例页面', resource: 'https://example.com/',
    surface: 'float' as const, surfaceFrame: { x: 200, y: 150, width: 520, height: 400 },
  })
  const wrapper = mount(CoreSplitBrowser, {
    props: {
      tab: tab as never,
      visible: true,
      pane: 'p1',
      services: {
        available: () => true,
        call: vi.fn(async (_id: string, action: string, options?: Record<string, unknown>) => { calls.push({ action, options }); return undefined }),
        subscribe: vi.fn(async () => () => {}),
        openExternal: vi.fn(async () => {}),
      },
    },
    attachTo: document.body,
  })
  wrappers.push(wrapper)
  const hostEl = wrapper.get('.split-browser-host').element as HTMLElement
  Object.defineProperty(hostEl, 'getBoundingClientRect', {
    configurable: true,
    value: () => {
      const frame = tab.surfaceFrame
      const inset = 8
      const x = frame.x + inset
      const y = frame.y + inset * 2
      const width = Math.max(1, frame.width - inset * 2)
      const height = Math.max(1, frame.height - inset * 3)
      return { x, y, width, height, top: y, left: x, right: x + width, bottom: y + height, toJSON: () => ({}) }
    },
  })
  return { wrapper, tab, calls, bounds: () => calls.filter(call => call.action === 'bounds') }
}

const settle = () => new Promise(resolve => setTimeout(resolve, 40))
const press = (wrapper: ReturnType<typeof mount>, x: number, y: number) => {
  wrapper.get('.split-browser-float-bar').element.dispatchEvent(new PointerEvent('pointerdown', { button: 0, clientX: x, clientY: y, bubbles: true }))
}
const moveTo = (x: number, y: number) => window.dispatchEvent(new PointerEvent('pointermove', { clientX: x, clientY: y, bubbles: true }))
const release = () => window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }))

// user:“拖动/缩放期间按帧节流下发 bounds（rAF 合并、同帧最多一次、矩形没变不发），让网页跟着容器走”
describe('浮窗跟手：拖动期间下发 bounds', () => {
  it('同一帧内多次 pointermove 只下发一次，且网页不再被隐藏', async () => {
    const { wrapper, calls } = mountFloat()
    await settle()
    const before = calls.filter(call => call.action === 'bounds').length
    press(wrapper, 260, 170)
    moveTo(280, 190); moveTo(300, 210); moveTo(320, 230)   // 同一帧三次
    await settle()
    const during = calls.filter(call => call.action === 'bounds').slice(before)
    expect(during).toHaveLength(1)
    // 关键断言：拖动中网页是可见的（interacting 不再把 float 的网页藏起来）
    expect(during[0].options?.visible).toBe(true)
    release()
    await settle()
  })

  it('矩形没变就不下发（同一 delta 重复不会追加 bounds）', async () => {
    const { wrapper, calls } = mountFloat()
    await settle()
    press(wrapper, 260, 170)
    moveTo(300, 210)
    await settle()
    const after1 = calls.filter(call => call.action === 'bounds').length
    moveTo(300, 210)   // 同一个位置再来一次：矩形完全相同
    await settle()
    expect(calls.filter(call => call.action === 'bounds').length).toBe(after1)
    release()
    await settle()
  })

  it('跟手时网页矩形随外框移动，不出现“先到原点再修正”的偏移', async () => {
    const { wrapper, calls, tab } = mountFloat()
    await settle()
    press(wrapper, 260, 170)
    moveTo(360, 270)
    await settle()
    const last = calls.filter(call => call.action === 'bounds').at(-1)!
    expect(last.options?.visible).toBe(true)
    expect(last.options?.x).toBe(tab.surfaceFrame.x + 8)
    expect(last.options?.y).toBe(tab.surfaceFrame.y + 16)
    release()
    await settle()
  })

  it('松手收口：最后一帧仍是可见的最终矩形，没有回弹', async () => {
    const { wrapper, calls, tab } = mountFloat()
    await settle()
    press(wrapper, 260, 170)
    moveTo(340, 260)
    await settle()
    const beforeRelease = { ...tab.surfaceFrame }
    release()
    await settle()
    const last = calls.filter(call => call.action === 'bounds').at(-1)!
    expect(last.options?.visible).toBe(true)
    expect(tab.surfaceFrame).toEqual(beforeRelease)
    expect(last.options?.x).toBe(beforeRelease.x + 8)
  })

  it('拖动中不再渲染“松手放下”占位（网页自己跟着走）', async () => {
    const { wrapper } = mountFloat()
    await settle()
    press(wrapper, 260, 170)
    moveTo(300, 210)
    await settle()
    expect(wrapper.find('.split-browser-float-placeholder').exists()).toBe(false)
    release()
    await settle()
  })
})
