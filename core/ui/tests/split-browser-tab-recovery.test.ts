import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'

// jsdom 里没有原生宿主：这里只把组件需要的三个出口换成可编程的替身。
// webviewBoundsArgs 与实现同形（标签 + 物理像素矩形），让 bounds 的入参形状保持真实。
vi.mock('../src/split/native', () => ({
  browserNative: vi.fn(),
  forgetBrowserTab: vi.fn(),
  hasSplitNative: () => true,
  subscribeBrowserEvents: vi.fn(async () => () => undefined),
  webviewBoundsArgs: (input: { surfaceId: string; contentRect: { x: number; y: number; width: number; height: number }; visible: boolean }) => ({
    label: input.surfaceId,
    x: Math.round(input.contentRect.x),
    y: Math.round(input.contentRect.y),
    width: Math.max(1, Math.round(input.contentRect.width)),
    height: Math.max(1, Math.round(input.contentRect.height)),
    visible: input.visible,
  }),
}))
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => () => undefined) }))
vi.mock('@/helpers/openUrl', () => ({ openExternalUrl: vi.fn() }))

afterEach(() => {
  document.body.replaceChildren()
  vi.restoreAllMocks()
})

function servicesFor(call: (id: string, action: string, options?: Record<string, unknown>) => Promise<unknown>) {
  return { available: () => true, call, subscribe: async () => () => undefined, openExternal: async () => undefined }
}

function tab(id: string) {
  return { id, kind: 'browser' as const, resource: 'https://example.com', title: 'example.com' }
}

async function settle() {
  await flushPromises()
  await new Promise(resolve => setTimeout(resolve, 40))
  await flushPromises()
}

// user:“内置浏览器出现：这个浏览器标签已经关闭 导致无法点击操作网页”+
// (两件事一起锁住：标签丢了要自愈重建，而不是挂一条永远挂着的错误；
//  错误条存在时也要继续把鼠标事件转发给网页，不能再出现“点了没反应”)。
describe('split browser lost native tab', () => {
  it('rebuilds the page instead of parking a dead-tab error banner', async () => {
    const actions: string[] = []
    let bounds = 0
    const call = vi.fn(async (_id: string, action: string) => {
      actions.push(action)
      if (action === 'bounds') {
        bounds += 1
        if (bounds === 1) throw { code: 'tab_not_found', message: '这个浏览器标签已经关闭', retriable: false }
      }
      return undefined
    })
    const wrapper = mount(CoreSplitBrowser, { props: { tab: tab('web-lost'), visible: false, services: servicesFor(call) } })
    try {
      await flushPromises()
      await wrapper.setProps({ visible: true })
      await settle()
      await settle()
      expect(actions.filter(action => action === 'create').length).toBeGreaterThanOrEqual(2)
      expect(wrapper.find('.split-content-error').exists()).toBe(false)
    } finally {
      wrapper.unmount()
    }
  })

  it('keeps forwarding pointer input while an error banner is visible', async () => {
    const calls: Array<{ id: string; action: string; options?: Record<string, unknown> }> = []
    const call = vi.fn(async (id: string, action: string, options?: Record<string, unknown>) => {
      calls.push({ id, action, options })
      if (action === 'bounds') throw { code: 'internal', message: '浏览器内部出错了', retriable: false }
      return undefined
    })
    const rect = { x: 0, y: 0, left: 0, top: 0, width: 200, height: 120, right: 200, bottom: 120, toJSON: () => ({}) } as DOMRect
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(rect)
    const wrapper = mount(CoreSplitBrowser, { props: { tab: tab('web-input'), visible: false, services: servicesFor(call) } })
    try {
      await flushPromises()
      await wrapper.setProps({ visible: true })
      await settle()
      expect(wrapper.find('.split-content-error').text()).toContain('浏览器内部出错了')
      const host = wrapper.find('.split-browser-host').element as HTMLElement
      host.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0, buttons: 1, clientX: 20, clientY: 20 }))
      await flushPromises()
      expect(calls.some(call => call.id === 'web-input' && call.action === 'input')).toBe(true)
    } finally {
      spy.mockRestore()
      wrapper.unmount()
    }
  })
})

// user:“内置浏览器出现：这个浏览器标签已经关闭 导致无法点击操作网页”+
// (用户的第一下点击就是证据：输入转发如果直接丢掉，页面会一直“点了没反应”；这里锁住点击触发的重建)。
describe('split browser dead tab on click', () => {
  it('rebuilds when the first forwarded click reports a dead tab', async () => {
    const actions: string[] = []
    const call = vi.fn(async (_id: string, action: string) => {
      actions.push(action)
      if (action === 'input') throw { code: 'tab_not_found', message: '这个浏览器标签已经关闭', retriable: false }
      return undefined
    })
    const rect = { x: 0, y: 0, left: 0, top: 0, width: 200, height: 120, right: 200, bottom: 120, toJSON: () => ({}) } as DOMRect
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(rect)
    const wrapper = mount(CoreSplitBrowser, { props: { tab: tab('web-click'), visible: false, services: servicesFor(call) } })
    try {
      await flushPromises()
      await wrapper.setProps({ visible: true })
      await settle()
      const host = wrapper.find('.split-browser-host').element as HTMLElement
      host.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0, buttons: 1, clientX: 20, clientY: 20 }))
      await settle()
      await settle()
      expect(actions.filter(action => action === 'create').length).toBeGreaterThanOrEqual(2)
      expect(wrapper.find('.split-content-error').exists()).toBe(false)
    } finally {
      spy.mockRestore()
      wrapper.unmount()
    }
  })
})
