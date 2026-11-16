import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PluginRegionBlocks from '../src/components/PluginRegionBlocks.vue'

// user:“确保视觉、功能和交互不退化”+(插件动作失败应显示错误并保留输入，运行时防止并发操作)。
describe('plugin action feedback', () => {
  it('reports a direct action failure and clears it on a successful retry', async () => {
    const rpc = vi.fn().mockRejectedValueOnce(new Error('连接失败')).mockResolvedValue({})
    const regions = [{ plugin: 'demo', region: 'main', order: 0, blocks: [], actions: [{ id: 'run', title: '运行', operation: 'demo.run' }] }] as any
    const wrapper = mount(PluginRegionBlocks, { props: { regions, requestRpc: rpc } })
    await wrapper.get('[data-action="run"]').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('连接失败')
    await wrapper.get('[data-action="run"]').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('preserves form data on failure, blocks concurrent actions and permits retry', async () => {
    let reject!: (reason: Error) => void
    const pending = new Promise<Record<string, unknown>>((_, fail) => { reject = fail })
    const rpc = vi.fn().mockReturnValueOnce(pending).mockResolvedValue({})
    const regions = [{ plugin: 'demo', region: 'main', order: 0, blocks: [], actions: [
      { id: 'run', title: '运行', operation: 'demo.run', input_schema: { properties: { name: { type: 'string', title: '名称' } } } },
      { id: 'other', title: '其他', operation: 'demo.other' },
    ] }] as any
    const wrapper = mount(PluginRegionBlocks, { props: { regions, requestRpc: rpc } })
    await wrapper.get('[data-action="run"]').trigger('click')
    await wrapper.get('input[type="text"]').setValue('保留内容')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[data-action="other"]').attributes('disabled')).toBeDefined()
    reject(new Error('示例失败')); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('示例失败')
    expect((wrapper.get('input[type="text"]').element as HTMLInputElement).value).toBe('保留内容')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(rpc).toHaveBeenLastCalledWith('demo.run', { name: '保留内容' })
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('form').exists()).toBe(false)
    wrapper.unmount()
  })
})
