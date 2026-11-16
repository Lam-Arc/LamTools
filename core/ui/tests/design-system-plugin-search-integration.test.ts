import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Editor from '../src/components/CorePluginSystemEditor.vue'
import LibrarySearchField from '../src/components/LibrarySearchField.vue'

describe('plugin search composition', () => {
  it('keeps search, clear, escape and slash focus behavior', async () => {
    const rpc = vi.fn(async (method: string) => method === 'plugin.system.list' ? { plugins: [
      { name: 'alpha', version: '1', description: 'Alpha', enabled: true, scope: 'global', root: '/alpha' },
      { name: 'beta', version: '1', description: 'Beta', enabled: false, scope: 'global', root: '/beta' },
    ], errors: [] } : {})
    const wrapper = mount(Editor, { attachTo: document.body, props: { requestRpc: rpc } })
    await flushPromises()
    expect(wrapper.findComponent(LibrarySearchField).exists()).toBe(true)
    const input = wrapper.get('[data-plugin-search]')
    expect(input.attributes('type')).toBe('text')
    await input.setValue('alpha')
    expect(wrapper.findAll('.plugin-card')).toHaveLength(1)
    await wrapper.get('button[aria-label="清除搜索"]').trigger('click')
    expect((input.element as HTMLInputElement).value).toBe('')
    expect(document.activeElement).toBe(input.element)
    await input.setValue('beta')
    await input.trigger('keydown', { key: 'Escape' })
    expect((input.element as HTMLInputElement).value).toBe('')
    ;(input.element as HTMLInputElement).blur()
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true }))
    expect(document.activeElement).toBe(input.element)
    wrapper.unmount()
  })
})
