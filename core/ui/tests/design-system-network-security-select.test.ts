import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SecurityView from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/SecurityView.vue'
import UiSelect from '../src/components/UiSelect.vue'

describe('network security shared selects', () => {
  it('selects an application and upload rate for the existing operation', async () => {
    const run = vi.fn(async () => ({}))
    const read = vi.fn(async () => ({ connections: [{ path: 'C:\\app.exe', process: '应用' }] }))
    const wrapper = mount(SecurityView, { props: { session: { state: { transactions: [] }, busy: '', run, read } } })
    await wrapper.findAll('button').find(button => button.text().includes('选择应用'))!.trigger('click')
    await flushPromises()
    wrapper.get('[data-network-application]').getComponent(UiSelect).vm.$emit('update:modelValue', 'C:\\app.exe')
    wrapper.get('[data-network-upload-limit]').getComponent(UiSelect).vm.$emit('update:modelValue', '40000000')
    await wrapper.vm.$nextTick()
    await wrapper.findAll('button').find(button => button.text().includes('申请限速'))!.trigger('click')
    expect(run).toHaveBeenCalledWith('system.apply', { kind: 'qos', program: 'C:\\app.exe', bits_per_second: 40000000 }, '已设置应用上传限速')
    wrapper.unmount()
  })
})
