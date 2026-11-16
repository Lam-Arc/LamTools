import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DirectCallView from '../src/components/DirectCallView.vue'

// user:“确保视觉、功能和交互不退化”+(调用历史筛选标签支持键盘并继续请求对应筛选结果)。
describe('direct call filter tabs', () => {
  it('navigates history filters and fetches the chosen type', async () => {
    const rpc = vi.fn(async (method: string) => method === 'direct.catalog' ? { models: [{ model_record_id: 'sample', model_id: 'sample', display_name: '示例', provider_id: 'local', output_type: 'text', has_api_key: true }], outputs: ['text'] } : { calls: [], total: 0 })
    const wrapper = mount(DirectCallView, { attachTo: document.body, props: { requestRpc: rpc, projectId: 'sample' } })
    await flushPromises()
    const tabs = wrapper.findAll('.dc-history-filters [role="tab"]')
    expect(tabs.length).toBeGreaterThan(1)
    expect(tabs[0].attributes('tabindex')).toBe('0')
    ;(tabs[0].element as HTMLElement).focus()
    await tabs[0].trigger('keydown', { key: 'ArrowRight' }); await flushPromises()
    expect(tabs[1].attributes('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[1].element)
    expect(rpc.mock.calls.filter(call => call[0] === 'direct.list').length).toBeGreaterThan(1)
    wrapper.unmount()
  })
})
