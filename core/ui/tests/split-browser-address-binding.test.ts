import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'
import type { BrowserNativeEvent } from '../src/split/native'

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

afterEach(() => { document.body.replaceChildren(); vi.clearAllMocks() })

// user:“浏览器地址栏里显示出 [object Object] 文本（不是输入的网址）”+
// (地址栏只允许显示字符串：标签上带着对象时显示空串，状态推送带对象时保留上一次有效地址。
//  这两条是 [object Object] 唯一的来源 —— `String(对象)`，所以断言里直接禁止这串文本出现在输入框。
//  真实设备上的复现路径也在这里：串起「挂载 → 收到状态事件 → 看输入框 value」。)
function harness() {
  const calls: Array<{ id: string; action: string; options: Record<string, unknown> }> = []
  let notify: ((event: BrowserNativeEvent) => void) | undefined
  const services = {
    available: () => true,
    call: vi.fn(async (id: string, action: string, options: Record<string, unknown> = {}) => { calls.push({ id, action, options }); return undefined }),
    subscribe: vi.fn(async (callback: (event: BrowserNativeEvent) => void) => { notify = callback; return () => { notify = undefined } }),
    openExternal: vi.fn(async () => undefined),
  }
  return { services, calls, push: (event: BrowserNativeEvent) => notify?.(event) }
}

function browserTab(resource: unknown) {
  return { id: 'web-a', kind: 'browser' as const, title: 'example.com', resource: resource as string }
}

function addressInput(wrapper: ReturnType<typeof mount>) {
  return wrapper.get('input[aria-label="网页地址"]').element as HTMLInputElement
}

describe('浏览器地址栏只显示字符串', () => {
  it('shows an empty address instead of [object Object] when the tab carries an object', async () => {
    const share = harness()
    const wrapper = mount(CoreSplitBrowser, { props: { tab: browserTab({ href: 'https://example.com' }), visible: false, services: share.services } })
    try {
      await flushPromises()
      const value = addressInput(wrapper).value
      expect(value).toBe('')
      expect(value).not.toContain('[object Object]')
    } finally { wrapper.unmount() }
  })

  it('keeps the last valid address when a state push carries an object url', async () => {
    const share = harness()
    const tab = browserTab('https://example.com/old')
    const wrapper = mount(CoreSplitBrowser, { props: { tab, visible: false, services: share.services } })
    try {
      await flushPromises()
      // 一次推送里塞对象：真机上只有这条路径有机会把对象变成地址栏文本。
      share.push({ id: 'web-a', url: { href: 'https://redirect.invalid/' } as unknown as string, title: { text: '标题对象' } as unknown as string })
      await nextTick(); await flushPromises()
      const value = addressInput(wrapper).value
      expect(value).toBe('https://example.com/old')
      expect(value).not.toContain('[object Object]')
      // 标签记录也不能被写脏：下次重启恢复的是字符串地址。
      expect(tab.resource).toBe('https://example.com/old')
      expect(tab.title).toBe('example.com')
    } finally { wrapper.unmount() }
  })

  it('still follows a real string state push', async () => {
    const share = harness()
    const tab = browserTab('https://example.com/old')
    const wrapper = mount(CoreSplitBrowser, { props: { tab, visible: false, services: share.services } })
    try {
      await flushPromises()
      share.push({ id: 'web-a', url: 'https://example.com/new', title: 'example.com' })
      await nextTick(); await flushPromises()
      expect(addressInput(wrapper).value).toBe('https://example.com/new')
      expect(tab.resource).toBe('https://example.com/new')
    } finally { wrapper.unmount() }
  })
})

// user:“输入没有真正进到输入框”+(两条都要能证明：手打的字不会被状态推送抹掉；
//  按 Enter 之后地址会写回标签记录，而不是只留在输入框里)。
describe('地址栏输入链路', () => {
  it('does not let a state push overwrite what is being typed', async () => {
    const share = harness()
    const tab = browserTab('https://example.com/old')
    const wrapper = mount(CoreSplitBrowser, { props: { tab, visible: false, services: share.services } })
    try {
      await flushPromises()
      const input = wrapper.get('input[aria-label="网页地址"]')
      await input.trigger('focus')
      await input.setValue('example.org/docs')
      share.push({ id: 'web-a', url: 'https://example.com/old', title: 'example.com', loading: true })
      await nextTick(); await flushPromises()
      expect(addressInput(wrapper).value).toBe('example.org/docs')
      // 标签记录仍然记着页面真实地址，草稿不会污染布局存档。
      expect(tab.resource).toBe('https://example.com/old')
    } finally { wrapper.unmount() }
  })

  it('writes a hand-typed address back to tab.resource and the native page', async () => {
    const share = harness()
    const tab = browserTab('')
    const wrapper = mount(CoreSplitBrowser, { props: { tab, visible: false, services: share.services } })
    try {
      await flushPromises()
      const input = wrapper.get('input[aria-label="网页地址"]')
      await input.trigger('focus')
      await input.setValue('example.com/docs')
      await wrapper.get('form.split-content-toolbar').trigger('submit')
      await flushPromises()
      expect(tab.resource).toBe('https://example.com/docs')
      expect(addressInput(wrapper).value).toBe('https://example.com/docs')
      expect(share.calls.some(call => call.action === 'create' && call.options.url === 'https://example.com/docs')).toBe(true)
    } finally { wrapper.unmount() }
  })
})
