import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import TitleBar from '../src/components/TitleBar.vue'

const originalTauriInternals = (window as typeof window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__

afterEach(() => {
  ;(window as typeof window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = originalTauriInternals
})

describe('Sunday window controls', () => {
  it('keeps the desktop-only window controls separate from full-width chrome', () => {
    const wrapper = mount(TitleBar, { props: { showInPreview: true } })
    expect(wrapper.findAll('[data-window-control]')).toHaveLength(3)
    expect(wrapper.find('.titlebar').exists()).toBe(false)
    wrapper.unmount()
  })

  // user:“窗口按钮改为纯 DOM 驱动，不再依赖原生命中区”+
  // (Rust 侧 set_maximize_button_bounds 已成空实现、也不再发 lamtools:maximize-hover，
  //  所以这条断言反过来锁：不再注册那个 bounds，拦截到废弃事件也不再改任何样式。
  //  按钮点击直接发命令的用例在 tests/titlebar-window-controls.test.ts)。
  it('no longer registers maximize bounds or mirrors the retired native hover', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined)
    const wrapper = mount(TitleBar, {
      props: { showInPreview: true },
    })
    await wrapper.vm.$nextTick()

    expect(invoke).not.toHaveBeenCalledWith('set_maximize_button_bounds', expect.anything())

    const maximize = wrapper.get('[data-window-control="maximize"]')
    expect(maximize.attributes('data-window-control')).toBe('maximize')
    window.dispatchEvent(new CustomEvent('lamtools:maximize-hover', { detail: true }))
    await wrapper.vm.$nextTick()
    expect(maximize.classes()).not.toContain('native-hover')
    wrapper.unmount()
  })

  it('leaves the controls out on mobile', () => {
    const wrapper = mount(TitleBar, { props: { showInPreview: true, hideOnMobile: true } })
    expect(wrapper.find('[data-window-controls]').exists()).toBe(false)
    wrapper.unmount()
  })
})
