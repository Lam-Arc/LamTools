import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CoreSettings from '../src/components/CoreSettings.vue'
import SundaySwitch from '../src/components/SundaySwitch.vue'
import { DEFAULT_THEME } from '../src/helpers/theme'

describe('update preference shared switch', () => {
  it('shows its current value and persists changes across remounts', async () => {
    localStorage.clear()
    const rpc = vi.fn(async () => ({}))
    const make = () => mount(CoreSettings, { props: { models: [], providers: [], modelGroups: [], catalogView: 'provider', commandShellPlatform: 'other', density: 'standard', theme: structuredClone(DEFAULT_THEME), requestRpc: rpc }, global: { stubs: { Teleport: true } } })
    const wrapper = make(); await flushPromises()
    await wrapper.get('[data-settings-section="about"]').trigger('click')
    const control = wrapper.get('[data-update-auto-check]')
    expect(control.findComponent(SundaySwitch).exists() || control.classes().includes('sunday-switch')).toBe(true)
    const input = control.get('input[role="switch"]')
    expect((input.element as HTMLInputElement).checked).toBe(true)
    await input.setValue(false)
    expect(localStorage.getItem('lamtools.update.autoCheck')).toBe('false')
    wrapper.unmount()
    const restored = make(); await flushPromises()
    await restored.get('[data-settings-section="about"]').trigger('click')
    expect((restored.get('[data-update-auto-check] input').element as HTMLInputElement).checked).toBe(false)
    restored.unmount(); localStorage.clear()
  })
})
