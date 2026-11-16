import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PluginRegionBlocks from '../src/components/PluginRegionBlocks.vue'

// user:“确保视觉、功能和交互不退化”+(参数表单遵循声明的必填字段，零和 false 是有效值)。
describe('plugin action required parameters', () => {
  it('requires declared text and number while allowing zero and false', async () => {
    const rpc = vi.fn(async () => ({}))
    const regions = [{ plugin: 'demo', region: 'main', order: 0, blocks: [], actions: [{ id: 'run', title: '运行', operation: 'demo.run', input_schema: { required: ['name', 'count', 'enabled'], properties: { name: { type: 'string', title: '名称' }, count: { type: 'number', title: '数量' }, enabled: { type: 'boolean', title: '启用' } } } }] }] as any
    const wrapper = mount(PluginRegionBlocks, { props: { regions, requestRpc: rpc } })
    await wrapper.get('[data-action="run"]').trigger('click')
    expect(wrapper.get('input[type="text"]').attributes('required')).toBeDefined()
    expect(wrapper.get('input[type="number"]').attributes('required')).toBeDefined()
    await wrapper.get('form').trigger('submit'); await flushPromises(); expect(rpc).not.toHaveBeenCalled()
    await wrapper.get('input[type="text"]').setValue('示例')
    await wrapper.get('form').trigger('submit'); await flushPromises(); expect(rpc).not.toHaveBeenCalled()
    await wrapper.get('input[type="number"]').setValue('0')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(rpc).toHaveBeenCalledWith('demo.run', { name: '示例', count: 0, enabled: false })
    wrapper.unmount()
  })
})
