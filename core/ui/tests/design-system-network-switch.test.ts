import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import ProxyView from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/ProxyView.vue'
import AdvancedView from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/AdvancedView.vue'
import SundaySwitch from '../src/components/SundaySwitch.vue'

describe('bundled network shared switches', () => {
  it('preserves the proxy connection action and disabled conditions', async () => {
    const toggleProxy = vi.fn()
    const session = reactive({ state: { proxy: { running: false, config_saved: true } }, busy: '', toggleProxy })
    const wrapper = mount(ProxyView, { props: { session }, global: { stubs: { NodePicker: true, ImportProfile: true } } })
    const control = wrapper.get('[data-proxy-switch]').getComponent(SundaySwitch)
    const input = control.get('input[role="switch"]')
    expect(input.attributes('aria-label')).toBe('代理连接')
    await input.setValue(true)
    expect(toggleProxy).toHaveBeenCalledOnce()
    await wrapper.vm.$nextTick()
    expect((input.element as HTMLInputElement).checked).toBe(false)
    session.busy = 'loading'
    await wrapper.vm.$nextTick()
    expect((input.element as HTMLInputElement).disabled).toBe(true)
    session.busy = ''
    session.state.proxy.config_saved = false
    await wrapper.vm.$nextTick()
    expect((input.element as HTMLInputElement).disabled).toBe(true)
    wrapper.unmount()
  })
  it('preserves schedule enablement and revision in the saved request', async () => {
    const run = vi.fn(async () => ({}))
    const session = reactive({ state: { revision: 9, settings: { sample_seconds: 5 }, automations: [{ target: 'example.com', enabled: true, interval_minutes: 30 }] }, busy: '', run })
    const wrapper = mount(AdvancedView, { props: { session } })
    const control = wrapper.getComponent(SundaySwitch)
    expect(control.props('size')).toBe('sm')
    await control.get('input[role="switch"]').setValue(false)
    expect(run).toHaveBeenCalledWith('automation.save', { revision: 9, automations: [expect.objectContaining({ target: 'example.com', enabled: false })] }, '定时检查已更新')
    await wrapper.vm.$nextTick()
    expect((control.get('input').element as HTMLInputElement).checked).toBe(true)
    wrapper.unmount()
  })
})
