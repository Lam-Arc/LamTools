import { mount, flushPromises } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'
import type { BrowserNativeEvent } from '../src/split/native'
import type { WorkspaceController } from '../src/workspace/context'
import { t } from '../src/i18n'
import {
  browserHomeVisible,
  greetingSlot,
  greetingStoredVisible,
  greetingText,
  homeQuickActionIds,
} from '../src/split/browserHome'

vi.mock('../src/split/native', () => ({
  browserNative: vi.fn().mockResolvedValue(undefined),
  forgetBrowserTab: vi.fn(),
  hasSplitNative: () => true,
  subscribeBrowserEvents: vi.fn(async () => () => undefined),
  webviewBoundsArgs: (input: { surfaceId: string; contentRect: { x: number; y: number; width: number; height: number }; visible: boolean }) => ({
    label: input.surfaceId,
    x: Math.round(input.contentRect.x), y: Math.round(input.contentRect.y),
    width: Math.max(1, Math.round(input.contentRect.width)), height: Math.max(1, Math.round(input.contentRect.height)),
    visible: input.visible,
  }),
}))
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => () => undefined) }))
vi.mock('@/helpers/openUrl', () => ({ openExternalUrl: vi.fn() }))

// user:“当浏览器标签没有地址（tab.resource 为空、尚未创建 webview）时，在 pane 内渲染一张首页而不是空白”+
// (这里钉的就是这条时序：首页出现 ⇔ 这个标签没有活着的网页；所以“没有 create 调用、也没有 bounds 下发”
//  本身就是“pane 内没有网页残留”的可断言证据)。

function harness(options: { failCreate?: boolean } = {}) {
  const calls: Array<{ id: string; action: string; options: Record<string, unknown> }> = []
  let notify: ((event: BrowserNativeEvent) => void) | undefined
  const services = {
    available: () => true,
    call: vi.fn(async (id: string, action: string, payload: Record<string, unknown> = {}) => {
      calls.push({ id, action, options: payload })
      if (options.failCreate && action === 'create') throw new Error('子 webview 创建失败')
      return undefined
    }),
    subscribe: vi.fn(async (callback: (event: BrowserNativeEvent) => void) => { notify = callback; return () => { notify = undefined } }),
    openExternal: vi.fn(async () => undefined),
  }
  return { services, calls, push: (event: BrowserNativeEvent) => notify?.(event) }
}

function browserTab(resource = '') {
  return { id: 'web-home', kind: 'browser' as const, title: '浏览器', resource }
}

function mountBrowser(tab = browserTab(), extra: Record<string, unknown> = {}) {
  const share = harness(extra.failCreate ? { failCreate: true } : {})
  const wrapper = mount(CoreSplitBrowser, { attachTo: document.body, props: { tab, visible: true, services: share.services, ...extra.props as object } as never, slots: extra.slots as never })
  return { wrapper, share, tab }
}

function homeInput(wrapper: ReturnType<typeof mount>) {
  return wrapper.get('[data-browser-home] input').element as HTMLInputElement
}
function addressInput(wrapper: ReturnType<typeof mount>) {
  return wrapper.get('input[aria-label="网页地址"]').element as HTMLInputElement
}
function created(wrapper: ReturnType<typeof mount>) {
  return wrapper.find('[data-browser-home]').exists()
}

beforeEach(() => { try { localStorage.clear() } catch { /* jsdom 一定有，但别让清理失败挡住测试 */ } })
afterEach(() => { document.body.replaceChildren(); vi.clearAllMocks(); vi.restoreAllMocks() })

describe('首页显隐条件', () => {
  it('没有地址、也没有 webview 时画首页', async () => {
    const { wrapper, share } = mountBrowser()
    try {
      await flushPromises()
      expect(created(wrapper)).toBe(true)
      expect(share.calls.filter(call => call.action === 'create')).toHaveLength(0)
      // 没有 webview 就不该有任何 bounds 下发：这就是“pane 内没有网页残留”的机器证据。
      expect(share.calls.filter(call => call.action === 'bounds')).toHaveLength(0)
    } finally { wrapper.unmount() }
  })

  it('标签已经有地址时先建网页，首页不出现', async () => {
    const { wrapper, share } = mountBrowser(browserTab('https://example.com/a'))
    try {
      await flushPromises()
      expect(share.calls.some(call => call.action === 'create')).toBe(true)
      expect(created(wrapper)).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('纯函数：有网页就不画首页，失败过就退回首页', () => {
    expect(browserHomeVisible({ resource: '', created: false })).toBe(true)
    expect(browserHomeVisible({ resource: '   ', created: false })).toBe(true)
    expect(browserHomeVisible({ resource: 'https://example.com/', created: false })).toBe(false)
    expect(browserHomeVisible({ resource: 'https://example.com/', created: false, failed: true })).toBe(true)
    expect(browserHomeVisible({ resource: '', created: true, failed: true })).toBe(false)
  })
})

describe('中央输入栏', () => {
  it('提交时复用地址栏那套解析：域名直接打开，其他交给搜索', async () => {
    const first = mountBrowser()
    try {
      await flushPromises()
      await first.wrapper.get('[data-browser-home] input').setValue('example.com')
      await first.wrapper.get('[data-browser-home] form').trigger('submit')
      await flushPromises()
      const create = first.share.calls.find(call => call.action === 'create')
      expect(create?.options.url).toBe('https://example.com/')
    } finally { first.wrapper.unmount() }

    const second = mountBrowser()
    try {
      await flushPromises()
      await second.wrapper.get('[data-browser-home] input').setValue('随便 搜一下')
      await second.wrapper.get('[data-browser-home] form').trigger('submit')
      await flushPromises()
      const create = second.share.calls.find(call => call.action === 'create')
      expect(create?.options.url).toBe('https://www.bing.com/search?q=%E9%9A%8F%E4%BE%BF%20%E6%90%9C%E4%B8%80%E4%B8%8B')
    } finally { second.wrapper.unmount() }
  })

  it('进入首页就聚焦，切回这个标签还会再聚焦', async () => {
    const { wrapper } = mountBrowser()
    try {
      await flushPromises()
      expect(document.activeElement).toBe(homeInput(wrapper))
      await wrapper.setProps({ visible: false })
      await flushPromises()
      ;(document.activeElement as HTMLElement | null)?.blur()
      await wrapper.setProps({ visible: true })
      await flushPromises()
      expect(document.activeElement).toBe(homeInput(wrapper))
    } finally { wrapper.unmount() }
  })

  it('Esc 清空输入并留在输入栏里', async () => {
    const { wrapper } = mountBrowser()
    try {
      await flushPromises()
      const input = wrapper.get('[data-browser-home] input')
      await input.setValue('https://example.com/')
      await input.trigger('keydown', { key: 'Escape' })
      expect((input.element as HTMLInputElement).value).toBe('')
      expect(document.activeElement).toBe(input.element)
    } finally { wrapper.unmount() }
  })

  it('Ctrl+L 把焦点交给顶部地址栏', async () => {
    const { wrapper } = mountBrowser()
    try {
      await flushPromises()
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'l', ctrlKey: true }))
      // 聚焦排在 nextTick 里：等一整轮微任务再把焦点读回来。
      await nextTick(); await flushPromises()
      expect(document.activeElement).toBe(addressInput(wrapper))
    } finally { wrapper.unmount() }
  })

  it('建不起来就退回首页，并把原因写出来', async () => {
    const tab = browserTab()
    const wrapper = mount(CoreSplitBrowser, {
      attachTo: document.body,
      props: { tab, visible: true, services: harness({ failCreate: true }).services } as never,
    })
    try {
      await flushPromises()
      await wrapper.get('[data-browser-home] input').setValue('broken.invalid')
      await wrapper.get('[data-browser-home] form').trigger('submit')
      await flushPromises()
      // 地址已经写回标签（用户输入不会丢），但网页没建起来：首页必须还在，而不是一张白屏。
      expect(tab.resource).toBe('https://broken.invalid/')
      expect(created(wrapper)).toBe(true)
      expect(wrapper.get('[role="alert"]').text()).toContain('子 webview 创建失败')
    } finally { wrapper.unmount() }
  })
})

describe('可选组件', () => {
  it('问候语按时段切换，关掉之后不再出现', async () => {
    expect(greetingSlot(5)).toBe('morning')
    expect(greetingSlot(11)).toBe('morning')
    expect(greetingSlot(12)).toBe('afternoon')
    expect(greetingSlot(17)).toBe('afternoon')
    expect(greetingSlot(18)).toBe('evening')
    expect(greetingSlot(4)).toBe('evening')
    expect(greetingText(9)).toBe('早上好')
    expect(greetingText(14)).toBe('下午好')
    expect(greetingText(21)).toBe('晚上好')
    expect(greetingStoredVisible('off')).toBe(false)
    expect(greetingStoredVisible(null)).toBe(true)

    const first = mountBrowser()
    try {
      await flushPromises()
      expect(first.wrapper.find('[data-browser-home-greeting]').exists()).toBe(true)
      await first.wrapper.get('[aria-label="隐藏问候语"]').trigger('click')
      expect(first.wrapper.find('[data-browser-home-greeting]').exists()).toBe(false)
      expect(localStorage.getItem('lamtools:browser-home-greeting')).toBe('off')
    } finally { first.wrapper.unmount() }

    const second = mountBrowser()
    try {
      await flushPromises()
      expect(second.wrapper.find('[data-browser-home-greeting]').exists()).toBe(false)
    } finally { second.wrapper.unmount() }
  })

  it('快捷入口只放真能落地的：没有控制器就只剩 Web', async () => {
    expect(homeQuickActionIds({ hasController: false, hasPane: false })).toEqual(['web'])
    expect(homeQuickActionIds({ hasController: true, hasPane: false })).toEqual(['web'])
    expect(homeQuickActionIds({ hasController: true, hasPane: true })).toEqual(['web', 'media'])

    const { wrapper } = mountBrowser()
    try {
      await flushPromises()
      expect(wrapper.findAll('[data-browser-home-action]').map(node => node.attributes('data-browser-home-action'))).toEqual(['web'])
    } finally { wrapper.unmount() }
  })

  it('文件和资料共用资料库分屏入口', async () => {
    const add = vi.fn()
    const controller = { add } as unknown as WorkspaceController
    const { wrapper } = mountBrowser(browserTab(), { props: { controller, pane: 'split-1' } })
    try {
      await flushPromises()
      expect(wrapper.findAll('[data-browser-home-action]').map(node => node.attributes('data-browser-home-action'))).toEqual(['web', 'media'])
      await wrapper.get('[data-browser-home-action="media"]').trigger('click')
      // 标签名沿用现有 i18n（zh-CN 的「资料库」是短名「库」），不在这里另造一个称呼。
      expect(add).toHaveBeenLastCalledWith('page', 'library', t('资料库'), 'split-1')
    } finally { wrapper.unmount() }
  })

  it('扩展位能把外部卡片挂到首页里', async () => {
    const { wrapper } = mountBrowser(browserTab(), { slots: { 'home-cards': () => h('div', { 'data-home-card': '' }, '天气') } })
    try {
      await flushPromises()
      expect(wrapper.find('[data-browser-home] [data-home-card]').text()).toBe('天气')
    } finally { wrapper.unmount() }
  })

  it('快捷入口关掉就记住，还能从首页设置再打开', async () => {
    const controller = { add: vi.fn() } as unknown as WorkspaceController
    const first = mountBrowser(browserTab(), { props: { controller, pane: 'split-1' } })
    try {
      await flushPromises()
      expect(first.wrapper.findAll('[data-browser-home-action]')).toHaveLength(3)
      await first.wrapper.get('[aria-label="隐藏快捷入口"]').trigger('click')
      expect(first.wrapper.findAll('[data-browser-home-action]')).toHaveLength(0)
      expect(localStorage.getItem('lamtools:browser-home-actions')).toBe('off')
    } finally { first.wrapper.unmount() }

    // 重开应用也还是关的：偏好跨会话，不是只在本次挂载里生效。
    const second = mountBrowser(browserTab(), { props: { controller, pane: 'split-1' } })
    try {
      await flushPromises()
      expect(second.wrapper.findAll('[data-browser-home-action]')).toHaveLength(0)
      // 关掉不是单向的：首页设置里同一行还能打开回来。
      await second.wrapper.get('[aria-label="首页设置"]').trigger('click')
      await second.wrapper.get('[data-browser-home-toggle="actions"]').trigger('click')
      expect(second.wrapper.findAll('[data-browser-home-action]')).toHaveLength(3)
      expect(localStorage.getItem('lamtools:browser-home-actions')).toBe('on')
    } finally { second.wrapper.unmount() }
  })

  it('问候语也能从首页设置重新打开', async () => {
    const { wrapper } = mountBrowser()
    try {
      await flushPromises()
      await wrapper.get('[aria-label="隐藏问候语"]').trigger('click')
      expect(wrapper.find('[data-browser-home-greeting]').exists()).toBe(false)
      await wrapper.get('[aria-label="首页设置"]').trigger('click')
      await wrapper.get('[data-browser-home-toggle="greeting"]').trigger('click')
      expect(wrapper.find('[data-browser-home-greeting]').exists()).toBe(true)
      expect(localStorage.getItem('lamtools:browser-home-greeting')).toBe('on')
    } finally { wrapper.unmount() }
  })
})
