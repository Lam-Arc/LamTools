import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PluginConfigPanel from '../src/components/PluginConfigPanel.vue'

// user:“确保视觉、功能和交互不退化”+(保存期间锁定表单避免新输入被旧请求结果覆盖)。
describe('plugin config save state', () => {
  it('locks all field types during save and re-enables them afterward', async () => {
    let finish!: () => void
    const pending = new Promise<void>(resolve => { finish = resolve })
    const rpc = vi.fn(async (method: string) => method.endsWith('.get') ? { schema: { properties: {
      name: { type: 'string', title: '名称' }, enabled: { type: 'boolean', title: '启用' }, mode: { type: 'string', title: '模式', enum: ['a', 'b'] }, count: { type: 'number', title: '数量' }, data: { type: 'object', title: '数据' },
    } }, config: { name: '旧值', enabled: true, mode: 'a', count: 1, data: {} } } : (await pending, {}))
    const wrapper = mount(PluginConfigPanel, { props: { pluginName: 'example', version: '1', description: '', requestRpc: rpc } })
    await flushPromises(); await wrapper.get('form').trigger('submit')
    expect(wrapper.get('input[type="text"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('input[type="checkbox"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('input[type="number"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.ui-select-trigger').attributes('disabled')).toBeDefined()
    finish(); await flushPromises()
    expect(wrapper.get('input[type="text"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('.ui-select-trigger').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
})
