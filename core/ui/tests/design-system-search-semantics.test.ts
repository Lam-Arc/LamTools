import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SearchShell from '../src/components/SearchShell.vue'

// user:“确保视觉、功能和交互不退化”+(全局搜索结果和键盘当前项可被辅助技术识别)。
describe('search result semantics', () => {
  it('can avoid stealing focus when embedded in a preview', async () => {
    const opener = document.createElement('button'); document.body.append(opener); opener.focus()
    const wrapper = mount(SearchShell, { attachTo: document.body, props: { requestRpc: async () => ({}), sessions: [], onJump: vi.fn(), autoFocus: false } })
    await flushPromises()
    expect(document.activeElement).toBe(opener)
    wrapper.unmount(); opener.remove()
  })
  it('exposes the active keyboard result and activates it', async () => {
    const open = vi.fn()
    const wrapper = mount(SearchShell, { props: { requestRpc: async () => ({}), sessions: [{ id: 'a', title: '任务甲', status: 'idle', updatedAt: '' }, { id: 'b', title: '任务乙', status: 'idle', updatedAt: '' }] as any, onJump: vi.fn(), onOpenSession: open } })
    await flushPromises()
    const input = wrapper.get('input.search-field-input')
    expect(input.attributes('role')).toBe('combobox')
    const list = wrapper.get('[role="listbox"]')
    expect(input.attributes('aria-controls')).toBe(list.attributes('id'))
    const options = wrapper.findAll('[role="option"]')
    expect(options).toHaveLength(2)
    await input.trigger('keydown', { key: 'ArrowDown' })
    const active = wrapper.find('[role="option"][aria-selected="true"]')
    expect(input.attributes('aria-activedescendant')).toBe(active.attributes('id'))
    await input.trigger('keydown', { key: 'Enter' })
    expect(open).toHaveBeenCalledWith(active.attributes('data-search-row')?.replace('recent-', ''))
    wrapper.unmount()
  })
})
