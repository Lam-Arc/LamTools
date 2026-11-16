import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MaterialsView from '../src/components/MaterialsView.vue'

// user:“确保视觉、功能和交互不退化”+(标签补全可用键盘选择，直接输入仍可创建)。
describe('material tag suggestions keyboard', () => {
  it('navigates and applies a suggested tag, preserving direct entry', async () => {
    const rows = [{ artifact_id: 'a', name: 'a.txt', kind: 'file', role: 'deliverable', path: 'workspace://a.txt', uri: 'workspace://a.txt', mime_type: 'text/plain', favorite: false, deleted: false, folder: '', updated_at: '2026-01-01', tags: [], rating: 0 }, { artifact_id: 'b', name: 'b.txt', kind: 'file', role: 'deliverable', path: 'workspace://b.txt', uri: 'workspace://b.txt', mime_type: 'text/plain', favorite: false, deleted: false, folder: '', updated_at: '2026-01-01', tags: ['button'], rating: 0 }]
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'artifact.list') return { artifacts: rows }
      if (method === 'artifact.stats') return {}
      if (method === 'artifact.tags') { const row = rows.find(item => item.artifact_id === params?.artifact_id)!; row.tags = params?.tags as string[]; return { artifact: row } }
      return {}
    })
    const wrapper = mount(MaterialsView, { attachTo: document.body, props: { projectId: 'p', workRoot: '/sample', requestRpc: rpc, transport: {} as never, uploadFiles: async () => {} } })
    await flushPromises()
    const input = wrapper.get('[data-material-tag-input="a"]')
    await input.trigger('click')
    await input.trigger('focus'); await input.setValue('but')
    expect(input.attributes('role')).toBe('combobox')
    await input.trigger('keydown', { key: 'Escape' })
    expect(input.attributes('aria-expanded')).toBe('false')
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(input.attributes('aria-expanded')).toBe('true')
    const selected = wrapper.get('[data-material-tag-suggest="button"]')
    expect(selected.attributes('aria-selected')).toBe('true')
    expect(input.attributes('aria-activedescendant')).toBe(selected.attributes('id'))
    await input.trigger('keydown', { key: 'Enter' }); await flushPromises()
    expect(rpc).toHaveBeenCalledWith('artifact.tags', expect.objectContaining({ artifact_id: 'a', tags: ['button'] }))
    await input.setValue('custom'); await input.trigger('keydown', { key: ' ' }); await flushPromises()
    expect(rpc).toHaveBeenLastCalledWith('artifact.tags', expect.objectContaining({ artifact_id: 'a', tags: ['button', 'custom'] }))
    await wrapper.get('[data-material="a"] .material-rating-star').trigger('keydown', { key: 'Enter' })
    expect(rpc.mock.calls.some(call => call[0] === 'artifact.open')).toBe(false)
    wrapper.unmount()
  })
})
