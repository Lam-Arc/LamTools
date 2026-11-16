import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import TransferView from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/TransferView.vue'
import UiSelect from '../src/components/UiSelect.vue'
describe('network transfer shared selects', () => {
  it('preserves numeric options, proxy availability and per-task limit action', async () => {
    const run = vi.fn(async () => null)
    const session = { state: { proxy: { running: false }, downloads: [] }, tasks: [{ gid: 'job', status: 'active', totalLength: 100, completedLength: 10 }], busy: '', run, loadTasks: vi.fn() }
    const wrapper = mount(TransferView, { props: { session } })
    wrapper.get('[data-transfer-connections]').getComponent(UiSelect).vm.$emit('update:modelValue', '4')
    wrapper.get('[data-transfer-speed]').getComponent(UiSelect).vm.$emit('update:modelValue', '1048576')
    await wrapper.get('input[aria-label="下载链接"]').setValue('https://example.com/file')
    await wrapper.findAll('button').find(button => button.text().includes('更多选项'))!.trigger('click')
    const route = wrapper.get('[data-transfer-route]').getComponent(UiSelect)
    expect(route.props('options').find((item: any) => item.value === 'proxy').disabled).toBe(true)
    route.vm.$emit('update:modelValue', 'direct')
    await wrapper.find('form').trigger('submit')
    expect(run).toHaveBeenCalledWith('transfer.add', expect.objectContaining({ connections: 4, bytes_per_second: 1048576, route: 'direct' }), '已开始下载')
    await wrapper.get('button[aria-label="展开下载详情"]').trigger('click')
    const taskLimit = wrapper.get('[data-transfer-task-limit]').getComponent(UiSelect)
    taskLimit.vm.$emit('update:modelValue', '0')
    expect(run).not.toHaveBeenCalledWith('transfer.action', expect.anything(), expect.anything())
    taskLimit.vm.$emit('update:modelValue', '5242880')
    await wrapper.vm.$nextTick()
    expect(run).toHaveBeenCalledWith('transfer.action', { gid: 'job', action: 'limit', bytes_per_second: 5242880 }, '下载限速已更新')
    wrapper.unmount()
  })
})
