import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import SearchShell from '../src/components/SearchShell.vue'

// user:“确保视觉、功能和交互不退化”+(输入变化或关闭后，旧搜索不能覆盖新状态或继续发起请求)。
describe('search lifecycle and stale results', () => {
  afterEach(() => vi.useRealTimers())
  it('invalidates in-flight results as soon as the query changes', async () => {
    vi.useFakeTimers()
    const deferred: Array<(value: Record<string, unknown>) => void> = []
    const rpc = vi.fn((method: string) => method === 'workspace.search' ? new Promise<Record<string, unknown>>(resolve => deferred.push(resolve)) : Promise.resolve({}))
    const wrapper = mount(SearchShell, { props: { requestRpc: rpc, sessions: [], onJump: vi.fn(), autoFocus: false } })
    const input = wrapper.get('.search-field-input')
    await input.setValue('旧查询'); await vi.advanceTimersByTimeAsync(300)
    expect(deferred).toHaveLength(2)
    await input.setValue('新查询')
    deferred.forEach(resolve => resolve({ results: [{ path: 'old.txt', content: '旧结果' }] }))
    await vi.advanceTimersByTimeAsync(0); await nextTick()
    expect(wrapper.text()).toContain('搜索中')
    expect(wrapper.text()).not.toContain('old.txt')
    await input.setValue(''); await nextTick()
    expect(wrapper.text()).not.toContain('old.txt')
    wrapper.unmount()
  })
  it('ignores a late failure after clearing the query', async () => {
    vi.useFakeTimers()
    const pending: Array<(error: Error) => void> = []
    const rpc = vi.fn((method: string) => method === 'workspace.search' ? new Promise<Record<string, unknown>>((_, reject) => pending.push(reject)) : Promise.resolve({}))
    const wrapper = mount(SearchShell, { props: { requestRpc: rpc, sessions: [], onJump: vi.fn(), autoFocus: false } })
    const input = wrapper.get('.search-field-input')
    await input.setValue('查询'); await vi.advanceTimersByTimeAsync(300)
    await input.setValue(''); pending.forEach(reject => reject(new Error('过期错误')))
    await vi.advanceTimersByTimeAsync(0); await nextTick()
    expect(wrapper.text()).not.toContain('过期错误')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('cancels a scheduled search when closed', async () => {
    vi.useFakeTimers()
    const rpc = vi.fn(async () => ({}))
    const wrapper = mount(SearchShell, { props: { requestRpc: rpc, sessions: [], onJump: vi.fn(), autoFocus: false } })
    await wrapper.get('.search-field-input').setValue('待搜索')
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(300)
    expect(rpc.mock.calls.filter(call => call[0] === 'workspace.search')).toHaveLength(0)
  })
})
