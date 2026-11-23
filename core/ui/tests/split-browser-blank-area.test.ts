import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'
import { browserAreaIssue, resolveBrowserBounds } from '../src/split/browserVisibility'
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

// user:“输入地址之后网页区域无效/空白”+
// (真机上这条问题有三种形态：网页没建出来、建出来但 visible=false、建出来但矩形为 0。
//  这组测试盯的是后两种里“明明什么都没显示，界面却当作已经打开”的那一种 ——
//  它必须同时满足两件事：原生侧收到的是 visible=false，且界面上有一句能照着做的话。
//  另外一条链路是正常的：提交地址后先 create，再把 visible=true 的矩形下发下去，绝不停在半路。)
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

function browserTab(resource = '') {
  return { id: 'web-a', kind: 'browser' as const, title: 'example.com', resource }
}

/** jsdom 里所有元素都没有尺寸；要测“这块屏真的能画网页”，就得只给宿主这一个元素一个矩形。 */
function stubHostRect(wrapper: ReturnType<typeof mount>, rect: { x: number; y: number; width: number; height: number }) {
  const element = wrapper.get('.split-browser-host').element as HTMLElement
  Object.defineProperty(element, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({ ...rect, top: rect.y, left: rect.x, right: rect.x + rect.width, bottom: rect.y + rect.height, toJSON: () => rect }),
  })
}

/** 组件把矩形下发排在下一帧（requestAnimationFrame），断言前要先让这一帧过去。 */
async function frame() { await new Promise<void>(resolve => requestAnimationFrame(() => resolve())) }

async function submitAddress(wrapper: ReturnType<typeof mount>, text: string) {
  const input = wrapper.get('input[aria-label="网页地址"]')
  await input.trigger('focus')
  await input.setValue(text)
  await wrapper.get('form.split-content-toolbar').trigger('submit')
  await flushPromises()
  await nextTick()
  await frame()
  await flushPromises()
}

describe('矩形为 0 时不会当成已显示', () => {
  it('给出可读原因，而不是把 1×1 隐藏矩形当成“已经打开”', () => {
    expect(browserAreaIssue(null)).toBe('unmounted')
    expect(browserAreaIssue({ x: 0, y: 0, width: 0, height: 0 })).toBe('collapsed')
    expect(browserAreaIssue({ x: 0, y: 0, width: 800, height: 600 })).toBe(null)
    // 矩形为 0 → 结论必须是“不显示”，并且位置/尺寸退化成 WebView2 能接受的 1×1。
    const hidden = resolveBrowserBounds({
      host: { x: 0, y: 0, width: 0, height: 0 },
      paneVisible: true,
      tabActive: true,
      workspaceHidden: false,
      overlayOpen: false,
      interacting: 'none',
      obscured: false,
    })
    expect(hidden.visible).toBe(false)
    expect(hidden.width).toBeGreaterThanOrEqual(1)
    expect(hidden.height).toBeGreaterThanOrEqual(1)
  })

  it('提交地址后这块屏没有面积：界面上说清原因，有面积后同一个网页会自己显示出来', async () => {
    const share = harness()
    const wrapper = mount(CoreSplitBrowser, { props: { tab: browserTab(''), visible: true, services: share.services } })
    try {
      await flushPromises()
      // jsdom 里宿主天然没有尺寸，正好是“窗口太窄 / 分屏被折叠”这一态。
      await submitAddress(wrapper, 'example.com/docs')

      const create = share.calls.find(call => call.action === 'create')
      expect(create, '地址解析成功就该去建网页').toBeTruthy()
      expect(create?.options.visible).toBe(false)
      const bounds = [...share.calls].reverse().find(call => call.action === 'bounds')
      expect(bounds?.options.visible, '矩形为 0 时不能把网页当成可见').toBe(false)
      expect(wrapper.text()).toContain('这块分屏还没有空间显示网页')

      // 空间回来了：resize 会触发一次重算，网页可见、那句解释必须自己收掉。
      stubHostRect(wrapper, { x: 200, y: 100, width: 800, height: 600 })
      window.dispatchEvent(new Event('resize'))
      await flushPromises(); await frame(); await flushPromises()
      const shown = [...share.calls].reverse().find(call => call.action === 'bounds')
      expect(shown?.options.visible, '有面积之后必须真的把网页放出来').toBe(true)
      expect(shown?.options.width).toBe(800)
      expect(wrapper.text()).not.toContain('这块分屏还没有空间显示网页')
    } finally { wrapper.unmount() }
  })
})

describe('提交地址后的下发顺序', () => {
  it('先 create，再把 visible=true 的矩形下发下去（不会停在“建好了但没显示”）', async () => {
    const share = harness()
    const wrapper = mount(CoreSplitBrowser, { props: { tab: browserTab(''), visible: true, services: share.services } })
    try {
      await flushPromises()
      stubHostRect(wrapper, { x: 200, y: 100, width: 800, height: 600 })
      await submitAddress(wrapper, 'example.com/docs')

      const createIndex = share.calls.findIndex(call => call.action === 'create')
      expect(createIndex, '提交地址后必须先建网页').toBeGreaterThanOrEqual(0)
      const create = share.calls[createIndex]
      expect(create.options).toMatchObject({ url: 'https://example.com/docs', x: 200, y: 100, width: 800, height: 600, visible: true })

      const boundsIndex = share.calls.findIndex((call, index) => index > createIndex && call.action === 'bounds' && call.options.visible === true)
      expect(boundsIndex, '建起来之后要补发一次可见矩形').toBeGreaterThan(createIndex)
      expect(share.calls[boundsIndex].options).toMatchObject({ x: 200, y: 100, width: 800, height: 600, visible: true })
      expect(wrapper.text()).not.toContain('这块分屏还没有空间显示网页')
    } finally { wrapper.unmount() }
  })
})
