import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import NetworkSettings from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkSettings.vue'
import UiSelect from '../src/components/UiSelect.vue'
describe('network settings shared selects', () => {
  it('keeps DNS, lookup and rule payloads and prevents empty interface submission', async () => {
    const run = vi.fn(async () => null)
    const session = { state: { revision: 7, rules: [{ domain: 'test.example', outbound: 'DIRECT' }] }, interfaces: [{ index: 4, name: '以太网' }], busy: '', run, read: vi.fn(async () => ({ interfaces: [] })) }
    const wrapper = mount(NetworkSettings, { props: { session } })
    await wrapper.get('[data-dns-toggle]').trigger('click')
    const save = wrapper.get('[data-dns-apply]')
    expect((save.element as HTMLButtonElement).disabled).toBe(true)
    wrapper.get('[data-network-interface]').getComponent(UiSelect).vm.$emit('update:modelValue', '4')
    await wrapper.vm.$nextTick()
    await save.trigger('click')
    expect(run).toHaveBeenCalledWith('system.apply', expect.objectContaining({ kind: 'dns', interface_index: 4 }), 'DNS 设置已更新')
    wrapper.get('[data-network-dns-provider]').getComponent(UiSelect).vm.$emit('update:modelValue', 'google')
    await wrapper.findAll('form')[0].trigger('submit')
    expect(run).toHaveBeenCalledWith('dns.query', expect.objectContaining({ provider: 'google' }))
    await wrapper.get('[data-rules-edit]').trigger('click')
    wrapper.get('[data-network-rule-outbound]').getComponent(UiSelect).vm.$emit('update:modelValue', 'PROXY')
    await wrapper.findAll('button').find(button => button.text().includes('保存规则'))!.trigger('click')
    expect(run).toHaveBeenCalledWith('rules.save', { revision: 7, rules: [expect.objectContaining({ outbound: 'PROXY' })] }, '规则已保存')
    wrapper.unmount()
  })
})
