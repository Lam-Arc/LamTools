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
})
