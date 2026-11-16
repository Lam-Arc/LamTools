import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import QuickPanel from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/QuickPanel.vue'
import UiSelect from '../src/components/UiSelect.vue'
const selectNode = vi.fn(async () => {})
const state = reactive({ state: { proxy: { running: true, config_saved: true } }, proxy: { proxies: { group: { type: 'Selector', all: ['DIRECT', 'node-a'], now: 'DIRECT' } } }, busy: '', systemProxyReady: true, accelerated: false, selectNode })
vi.mock('../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/session.mjs', () => ({ useNetwork: () => state }))
describe('network quick node selector', () => {
  it('keeps direct and named choices and performs the existing selection action', async () => {
    const wrapper = mount(QuickPanel, { props: { context: {} } })
    const select = wrapper.get('[data-network-quick-node]').getComponent(UiSelect)
    expect(select.props('modelValue')).toBe('DIRECT')
    select.vm.$emit('update:modelValue', 'node-a')
    expect(selectNode).toHaveBeenCalledWith('group', 'node-a')
    state.busy = 'busy'
    await wrapper.vm.$nextTick()
    expect(select.props('disabled')).toBe(true)
    wrapper.unmount()
  })
})
