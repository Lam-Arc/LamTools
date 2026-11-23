import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { overlayActive, overlayDepth, openOverlay, resetBrowserOverlays } from '../src/split/browserOverlays'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); resetBrowserOverlays() })

function mountBrowser(options: { resource?: string; visible?: boolean } = {}) {
  const calls: Array<{ action: string; options?: Record<string, unknown> }> = []
  const controller = {
    add: vi.fn(() => 'new-tab'),
    state: { panes: { p1: { activeTab: 't1', tabs: [{ id: 't1', kind: 'browser', title: 'x', resource: '' }] } } },
  }
  const wrapper = mount(CoreSplitBrowser, {
    props: {
      tab: { id: 't1', kind: 'browser' as const, title: 'example.com', resource: options.resource ?? '' },
      visible: options.visible ?? false,
      pane: 'p1',
      controller: controller as never,
      services: {
        available: () => true,
        call: vi.fn(async (_id: string, action: string, payload?: Record<string, unknown>) => { calls.push({ action, options: payload }); return undefined }),
        subscribe: vi.fn(async () => () => {}),
        openExternal: vi.fn(async () => {}),
      },
    },
    attachTo: document.body,
  })
  wrappers.push(wrapper)
  return { wrapper, calls }
}

// user:“页眉上要留的就是前进、返回、刷新、地址栏和一个『更多』”+
// (五个槽位是硬约束：页内查找/缩放/站点/新建标签都不许再占页眉，全部只在「更多」里出现)。
describe('浏览器页眉：五个槽位 + 更多分组菜单', () => {
  it('页眉只有五个槽位，查找与缩放不再平铺在页眉上', () => {
    const { wrapper } = mountBrowser()
    const slots = wrapper.findAll('[data-browser-slot]')
    expect(slots.map(slot => slot.attributes('data-browser-slot'))).toEqual(['back', 'forward', 'reload', 'address', 'more'])
    expect(wrapper.find('[data-browser-slot="address"]').attributes('type')).toBe('text')
    // 旧页眉里的临时按钮不能回流。
    expect(wrapper.findAll('button').some(button => button.attributes('title') === '页内查找')).toBe(false)
    expect(wrapper.findAll('button').some(button => button.attributes('title') === '站点操作')).toBe(false)
    expect(wrapper.find('.split-browser-zoom').exists()).toBe(false)
  })

  it('更多菜单仅保留缩放、查找、下载、默认浏览器四项必要能力', async () => {
    // 这条要验证“点得到并生效”，所以先让网页建起来（否则缩放项按设计是置灰的）。
    const { wrapper, calls } = mountBrowser({ resource: 'https://example.com/', visible: true })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()
    await wrapper.get('[data-browser-more]').trigger('click')
    const menu = wrapper.get('[data-browser-more-menu]')
    const ids = menu.findAll('[data-browser-more-item]').map(item => item.attributes('data-browser-more-item'))
    expect(ids).toEqual(['zoom-out', 'zoom-reset', 'zoom-in', 'find', 'downloads', 'external'])
    // 缩放菜单项走的是同一个 zoomStep。
    await wrapper.get('[data-browser-more-item="zoom-in"]').trigger('click')
    expect(calls.filter(call => call.action === 'zoom').at(-1)).toEqual({ action: 'zoom', options: { action: 'in' } })
  })

  it('没有网页时不可用的项置灰并写明原因', async () => {
    const { wrapper } = mountBrowser()
    await wrapper.get('[data-browser-more]').trigger('click')
    const find = wrapper.get('[data-browser-more-item="find"]')
    expect(find.attributes('disabled')).toBeDefined()
    expect(find.text()).toContain('还没有网页')
    expect(wrapper.get('[data-browser-more-item="zoom-reset"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-browser-more-item="downloads"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-browser-more-item="external"]').attributes('disabled')).toBeUndefined()
  })
})

// user:“把「有浮层」这件事统一登记，让网页无条件让位…支持嵌套计数”+
// (菜单开着就必须藏网页，两层叠着时关一层仍然藏着；关完才恢复)。
describe('浮层登记：网页让位', () => {
  it('嵌套两层时只关一层仍然算“有浮层”', () => {
    expect(overlayActive()).toBe(false)
    const first = openOverlay('context-menu')
    const second = openOverlay('browser-more-menu')
    expect(overlayDepth.value).toBe(2)
    expect(overlayActive()).toBe(true)
    first()
    expect(overlayDepth.value).toBe(1)
    expect(overlayActive()).toBe(true)
    second()
    expect(overlayDepth.value).toBe(0)
    expect(overlayActive()).toBe(false)
  })

  it('释放函数重复调用只扣一次（卸载与手动关闭各来一次也不会把网页提前放出来）', () => {
    const release = openOverlay('x')
    release(); release(); release()
    expect(overlayDepth.value).toBe(0)
  })

  it('打开与关闭更多菜单会登记/注销浮层，网页据此让位', async () => {
    const { wrapper } = mountBrowser()
    expect(overlayActive()).toBe(false)
    await wrapper.get('[data-browser-more]').trigger('click')
    expect(overlayActive()).toBe(true)
    await wrapper.get('[data-browser-more]').trigger('click')
    expect(overlayActive()).toBe(false)
  })
})

// user:“补一条自检：菜单打开 → 下发的 bounds 必须是 visible:false 且工具栏仍在 DOM 中可见；
// 菜单关闭 → 下一帧下发 visible:true”+
// (网页让位是有意的，但界面不能像“崩了”：宿主区要有占位，工具栏必须一直在)。
describe('更多菜单：让位与恢复', () => {
  it('打开时让位且工具栏仍在、占位出现；关闭后下一帧恢复', async () => {
    const { wrapper, calls } = mountBrowser({ resource: 'https://example.com/', visible: true })
    const hostEl = wrapper.get('.split-browser-host').element as HTMLElement
    Object.defineProperty(hostEl, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ x: 0, y: 100, width: 800, height: 600, top: 100, left: 0, right: 800, bottom: 700, toJSON: () => ({}) }),
    })
    await new Promise(resolve => setTimeout(resolve, 0))
    await wrapper.vm.$nextTick()
    const lastBounds = () => [...calls].reverse().find(call => call.action === 'bounds')

    await wrapper.get('[data-browser-more]').trigger('click')
    await wrapper.vm.$nextTick()
    expect(lastBounds()?.options?.visible).toBe(false)
    // 工具栏（五个槽位）一个都不能少：菜单是 DOM，网页让位不该牵连页眉。
    expect(wrapper.find('[data-browser-slot="more"]').exists()).toBe(true)
    expect(wrapper.find('[data-browser-slot="address"]').exists()).toBe(true)
    expect(wrapper.find('[data-browser-slot="back"]').exists()).toBe(true)
    // 宿主区不再是空白：有一层与主题一致的占位。
    expect(wrapper.find('[data-browser-yield]').exists()).toBe(true)

    await wrapper.get('[data-browser-more]').trigger('click')
    await wrapper.vm.$nextTick()
    await new Promise(resolve => setTimeout(resolve, 40))
    expect(wrapper.find('[data-browser-yield]').exists()).toBe(false)
    expect(lastBounds()?.options?.visible).toBe(true)
    expect(wrapper.find('[data-browser-more-menu]').exists()).toBe(false)
  })
})

// user:“单一登记口：嵌套计数、释放幂等、reset 只给测试/卸载”+
// (两层浮层叠着时，关掉一层仍然藏着网页；同一个 release 调两次只能扣一次)。
describe('browserOverlays 登记契约', () => {
  it('嵌套计数 + 同 release 只扣一次', () => {
    const releaseA = openOverlay('menu')
    const releaseB = openOverlay('modal')
    expect(overlayDepth()).toBe(2)
    expect(overlayDepth.value).toBe(2)
    expect(overlayActive()).toBe(true)

    releaseA()
    releaseA()
    expect(overlayDepth()).toBe(1)

    releaseB()
    expect(overlayDepth()).toBe(0)
    expect(overlayActive()).toBe(false)
  })

  it('resetBrowserOverlays 归零', () => {
    openOverlay('a')
    openOverlay('b')
    resetBrowserOverlays()
    expect(overlayDepth()).toBe(0)
    expect(overlayActive()).toBe(false)
  })
})
