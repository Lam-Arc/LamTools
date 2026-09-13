import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import TitleBar from '../src/components/TitleBar.vue'

const originalTauriInternals = (window as typeof window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__

afterEach(() => {
  ;(window as typeof window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = originalTauriInternals
})

describe('TitleBar mobile pairing', () => {
  it('opens the phone card and displays the current six-digit code', async () => {
    const invoke = vi.fn()
    ;(window as typeof window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = { invoke }
    const wrapper = mount(TitleBar, {
      props: {
        modeLabel: 'Agent',
        canToggleMode: false,
        mobilePairingCode: '012345',
        mobilePairingExpiresAtMs: Date.now() + 300_000,
      },
    })

    const trigger = wrapper.get('.mobile-pairing-trigger')
    expect(wrapper.get('.titlebar-left .brand-name').text()).toBe('Sunday')
    expect(wrapper.get('.titlebar-left .brand-tagline').text()).toBe('AI software')
    expect(wrapper.get('.titlebar-left .sunday-logo').attributes('aria-hidden')).toBe('true')
    expect(wrapper.get('.titlebar-left .sunday-logo').classes()).not.toContain('sunday-logo--surface')
    await trigger.trigger('click')

    expect(wrapper.get('.mobile-pairing-card').text()).toContain('012345')
    expect(trigger.attributes('aria-expanded')).toBe('true')

    await wrapper.get('.mobile-pairing-close').trigger('click')
    expect(wrapper.find('.mobile-pairing-card').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps pairing behind More and requests a code explicitly', async () => {
    ;(window as typeof window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = { invoke: vi.fn() }
    const wrapper = mount(TitleBar, {
      props: { modeLabel: 'Agent', canToggleMode: false },
    })

    await wrapper.get('.mobile-pairing-trigger').trigger('click')

    expect(wrapper.emitted('mobilePairingCreate')).toBeUndefined()
    expect(wrapper.get('.mobile-pairing-card').text()).toContain('尚未生成配对码')
    await wrapper.get('.mobile-pairing-action').trigger('click')
    expect(wrapper.emitted('mobilePairingCreate')).toHaveLength(1)
    wrapper.unmount()
  })

  it('registers the maximize button bounds and reflects native hover state', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined)
    ;(window as typeof window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = { invoke }
    const wrapper = mount(TitleBar, {
      props: { modeLabel: 'Agent', canToggleMode: false },
    })

    await vi.waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('set_maximize_button_bounds', expect.objectContaining({
        x: expect.any(Number),
        top: expect.any(Number),
        width: expect.any(Number),
        height: expect.any(Number),
      }))
    })

    const maximize = wrapper.get('.window-controls .ctrl-btn:nth-child(2)')
    window.dispatchEvent(new CustomEvent('lamtools:maximize-hover', { detail: true }))
    await wrapper.vm.$nextTick()
    expect(maximize.classes()).toContain('native-hover')

    window.dispatchEvent(new CustomEvent('lamtools:maximize-hover', { detail: false }))
    await wrapper.vm.$nextTick()
    expect(maximize.classes()).not.toContain('native-hover')
    wrapper.unmount()
  })
})
