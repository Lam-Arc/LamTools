import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CoreSplitBrowser from '../src/components/CoreSplitBrowser.vue'
import { browserNative } from '../src/split/native'

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

afterEach(() => { document.body.replaceChildren(); vi.clearAllMocks(); localStorage.clear() })

// user:“审查分屏代码，并优化”+(恢复的后台浏览器标签不预建子 WebView，等标签真正显示时才加载网页)。
describe('split browser lazy creation', () => {
  it('waits for the tab to become visible before creating the native page', async () => {
    const wrapper = mount(CoreSplitBrowser, { props: {
      tab: { id: 'web-a', kind: 'browser', resource: 'https://example.com', title: 'example.com' },
      visible: false,
    } })
    try {
      await flushPromises()
      expect(browserNative).not.toHaveBeenCalled()
      await wrapper.setProps({ visible: true }); await nextTick(); await flushPromises()
      expect(browserNative).toHaveBeenCalledWith('web-a', 'create', expect.objectContaining({ url: 'https://example.com/' }))
    } finally { wrapper.unmount() }
  })
})
