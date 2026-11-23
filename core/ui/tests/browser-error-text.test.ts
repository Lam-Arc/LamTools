import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'
import type { BrowserNativeEvent } from '../src/split/native'
import { errorCode, errorRetriable, errorText } from '../src/split/browserErrorText'

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

// user:“输入地址之后回车无反应；同时地址栏下方出现 [object Object] 文本”+
// (这里钉住三件事：① 回车真的会发起创建/导航；② 创建失败给的是人话；
//  ③ 任何对象（Rust 的 {code,message}、事件里被塞成对象的 message）都不许画成 [object Object])。

interface Call { id: string; action: string; options: Record<string, unknown> }

function harness(config: { fail?: unknown; boundsRejectOnce?: string } = {}) {
  const calls: Call[] = []
  let notify: ((event: BrowserNativeEvent) => void) | undefined
  let boundsRejected = false
  const services = {
    available: () => true,
    call: vi.fn(async (id: string, action: string, payload: Record<string, unknown> = {}) => {
      calls.push({ id, action, options: payload })
      if (config.boundsRejectOnce && action === 'bounds' && payload.visible === true && !boundsRejected) {
        boundsRejected = true
        throw config.boundsRejectOnce === 'tab_inactive'
          ? { code: 'tab_inactive', message: '后台标签不能占据可见区域', retriable: false }
          : { code: 'internal', message: { nested: true }, retriable: false }
      }
      if (config.fail !== undefined && action === 'create') throw config.fail
      return undefined
    }),
    subscribe: vi.fn(async (callback: (event: BrowserNativeEvent) => void) => { notify = callback; return () => { notify = undefined } }),
    openExternal: vi.fn(async () => undefined),
  }
  return { services, calls, push: (event: BrowserNativeEvent) => notify?.(event) }
}

function tab(resource = '') { return { id: 'web-err', kind: 'browser' as const, title: '浏览器', resource } }

function mountWith(share: ReturnType<typeof harness>, resource = '') {
  return mount(CoreSplitBrowser, { attachTo: document.body, props: { tab: tab(resource), visible: true, services: share.services } as never })
}

// 只断言“画出来的字”：wrapper.html() 会把模板注释也算进去，而注释里本来就写着
// “[object Object]”这四个字（记录这个 bug 的说明），拿它当证据会自我干扰。
function shownText(wrapper: ReturnType<typeof mount>) { return wrapper.text() }

/** jsdom 不一定给 requestAnimationFrame：用定时器替身，让 queueSync 的下一帧可预测。 */
function stubFrame() {
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(0), 0) as unknown as number)
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
}
/** 把“下一帧 + 微任务”跑干净：同步矩形、重试都在这一串里发生。 */
async function settle(rounds = 4) {
  for (let index = 0; index < rounds; index += 1) {
    await flushPromises()
    await new Promise(resolve => setTimeout(resolve, 5))
  }
  await flushPromises()
}

beforeEach(() => { stubFrame(); try { localStorage.clear() } catch { /* jsdom 一定有，这里是防御 */ } })
afterEach(() => { document.body.replaceChildren(); vi.clearAllMocks(); vi.restoreAllMocks() })

describe('错误文本归一化（纯函数）', () => {
  it('对象失败取 message，取不到就按错误码说人话，绝不返回 [object Object]', () => {
    expect(errorText({ code: 'tab_not_found', message: '这个浏览器标签已经关闭', retriable: false })).toBe('这个浏览器标签已经关闭')
    expect(errorText({ code: 'tab_inactive' })).toBe('这个标签现在在后台，切回来再试一次')
    expect(errorText({ code: 'internal', message: { nested: true } })).toBe('浏览器内部出错了')
    expect(errorText({ message: { nested: true } })).toBe('操作没有完成，请再试一次')
    expect(errorText(new Error('子 webview 创建失败'))).toBe('子 webview 创建失败')
    expect(errorText('请输入完整的网页地址')).toBe('请输入完整的网页地址')
    // 协议层原文不该出现在界面上
    expect(errorText('failed to invoke browser_open: boom')).toBe('操作没有完成，请再试一次')
    expect(errorText(null)).toBe('操作没有完成，请再试一次')
    expect(errorText(undefined, '')).toBe('')
    // 任何输入都不产生 [object Object]
    for (const value of [{}, [], { code: 'unknown' }, { message: {} }, 42]) {
      expect(errorText(value)).not.toContain('[object Object]')
    }
    expect(errorCode({ code: 'invalid_bounds' })).toBe('invalid_bounds')
    expect(errorRetriable({ retriable: true })).toBe(true)
    expect(errorRetriable('字符串')).toBe(false)
  })
})

describe('回车提交与失败提示', () => {
  it('输入网址回车会发起创建，并把解析后的地址写回标签', async () => {
    const share = harness()
    const wrapper = mountWith(share)
    try {
      await flushPromises()
      await wrapper.get('input[aria-label="网页地址"]').setValue('example.com')
      await wrapper.get('form.split-content-toolbar').trigger('submit')
      await settle()
      const create = share.calls.find(call => call.action === 'create')
      expect(create?.options.url).toBe('https://example.com/')
      // 创建成功之后才建出网页：先后两次下发（先隐藏再显示）都以真实矩形为准。
      expect(share.calls.some(call => call.action === 'bounds')).toBe(true)
    } finally { wrapper.unmount() }
  })

  it('创建失败（Rust 对象形状）显示可读原因，且页面里没有 [object Object]', async () => {
    const share = harness({ fail: { code: 'tab_not_found', message: '这个浏览器标签已经关闭', retriable: false } })
    const wrapper = mountWith(share)
    try {
      await flushPromises()
      await wrapper.get('input[aria-label="网页地址"]').setValue('example.com')
      await wrapper.get('form.split-content-toolbar').trigger('submit')
      await settle()
      const alert = wrapper.get('[role="alert"]')
      expect(alert.text()).toContain('这个浏览器标签已经关闭')
      expect(shownText(wrapper)).not.toContain('[object Object]')
    } finally { wrapper.unmount() }
  })

  it('状态事件里塞对象也不出现 [object Object]', async () => {
    const share = harness()
    const wrapper = mountWith(share)
    try {
      await flushPromises()
      share.push({ id: 'web-err', error: { code: 'internal', message: { nested: true }, retriable: false } as never })
      await nextTick()
      expect(wrapper.get('[role="alert"]').text()).toContain('浏览器内部出错了')
      // 地址/标题被塞成对象时，界面回落到空字符串，不打印对象
      share.push({ id: 'web-err', url: {} as never, title: {} as never, loading: false })
      await nextTick()
      expect(shownText(wrapper)).not.toContain('[object Object]')
      // 授权提示的 message 被塞成对象时同样如此
      share.push({ id: 'web-err', permission: { host: 'example.com', kind: 'camera', decision: 'deny', message: { nested: true } as never } })
      await nextTick()
      expect(shownText(wrapper)).not.toContain('[object Object]')
    } finally { wrapper.unmount() }
  })

  it('可见 bounds 被 tab_inactive 拒掉时先激活再重试，而不是停在空白', async () => {
    // jsdom 里所有元素的 getBoundingClientRect 都是 0，可见性判定会一直落在 false；
    // 这里给宿主一个真实矩形，才走得到「可见 bounds 被拒」这条自救路径。
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      x: 40, y: 80, width: 800, height: 600, top: 80, left: 40, right: 840, bottom: 680, toJSON: () => ({}),
    } as DOMRect)
    const share = harness({ boundsRejectOnce: 'tab_inactive' })
    const wrapper = mountWith(share, 'https://example.com/')
    try {
      await flushPromises()
      // 同步矩形排在下一帧：stubFrame + settle 把这一帧与随后的重试都走完。
      await settle(6)
      expect(share.calls.some(call => call.action === 'activate')).toBe(true)
      const visibleBounds = share.calls.filter(call => call.action === 'bounds' && call.options.visible === true)
      expect(visibleBounds.length).toBeGreaterThanOrEqual(2)
      expect(shownText(wrapper)).not.toContain('[object Object]')
    } finally { wrapper.unmount() }
  })
})
