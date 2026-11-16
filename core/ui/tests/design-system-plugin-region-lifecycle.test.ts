import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PluginRegionBlocks from '../src/components/PluginRegionBlocks.vue'

const regions = (dangerous: boolean) => [{ plugin: 'demo', region: 'main', order: 0, blocks: [], actions: [{ id: 'run', title: '运行', operation: 'demo.run', dangerous }] }] as any
// user:“确保视觉、功能和交互不退化”+(区域关闭时撤销未完成授权，避免离开页面后继续操作)。
describe('plugin region consent lifecycle', () => {
  it('closes a pending dangerous-action confirmation without running it', async () => {
    const rpc = vi.fn(async () => ({}))
    const wrapper = mount(PluginRegionBlocks, { attachTo: document.body, props: { regions: regions(true), requestRpc: rpc } })
    await wrapper.get('[data-action="run"]').trigger('click'); await flushPromises()
    expect(document.querySelector('[role="dialog"]')).toBeTruthy()
    wrapper.unmount(); await flushPromises()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(rpc).not.toHaveBeenCalled()
  })
  it('ignores an approval that arrives after unmount', async () => {
    let finish!: (result: Record<string, unknown>) => void
    const rpc = vi.fn(() => new Promise<Record<string, unknown>>(resolve => { finish = resolve }))
    const wrapper = mount(PluginRegionBlocks, { attachTo: document.body, props: { regions: regions(false), requestRpc: rpc } })
    await wrapper.get('[data-action="run"]').trigger('click')
    wrapper.unmount()
    finish({ approval: { id: 'late', operation: '操作', impact: '示例' } }); await flushPromises()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(rpc).toHaveBeenCalledTimes(1)
  })
  it('closes a backend approval without sending a decision after unmount', async () => {
    const rpc = vi.fn(async () => ({ approval: { id: 'approval', operation: '操作', impact: '示例' } }))
    const wrapper = mount(PluginRegionBlocks, { attachTo: document.body, props: { regions: regions(false), requestRpc: rpc } })
    await wrapper.get('[data-action="run"]').trigger('click'); await flushPromises()
    expect(document.querySelector('[role="dialog"]')).toBeTruthy()
    wrapper.unmount(); await flushPromises()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(rpc).toHaveBeenCalledTimes(1)
  })
})
