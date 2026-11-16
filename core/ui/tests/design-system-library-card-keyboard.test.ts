import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MemoryView from '../src/components/MemoryView.vue'
import PlanLibraryView from '../src/components/PlanLibraryView.vue'

// user:“确保视觉、功能和交互不退化”+(菜单按钮的回车不应打开卡片，卡片自身仍可打开)。
describe('library card keyboard interaction', () => {
  it('keeps memory menu activation separate from opening files and folders', async () => {
    const request = vi.fn(async (method: string) => {
      if (method === 'memory.tree') return { entries: [
        { path: '笔记.md', is_dir: false, size: 1, modified: '', summary: '' },
        { path: '目录', is_dir: true, size: 0, modified: '', summary: '' },
      ] }
      if (method === 'memory.projects') return { projects: [] }
      return { content: '内容' }
    })
    const wrapper = mount(MemoryView, { props: { requestRpc: request as any, client: { list: async () => [] } as any, platform: 'desktop' } })
    await wrapper.get('[data-memory-tier="global"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('[data-memory-entry]').exists()).toBe(true))
    await wrapper.get('[data-memory-folder] .card-menu-btn').trigger('keydown', { key: 'Enter' })
    expect(wrapper.find('[data-memory-entry]').exists()).toBe(true)
    await wrapper.get('[data-memory-entry] .card-menu-btn').trigger('keydown', { key: 'Enter' })
    expect(request.mock.calls.some(([method]) => method === 'memory.read')).toBe(false)
    await wrapper.get('[data-memory-view-toggle] button[aria-label="列表视图"]').trigger('click')
    await wrapper.get('[data-memory-entry] .card-menu-btn').trigger('keydown', { key: 'Enter' })
    expect(request.mock.calls.some(([method]) => method === 'memory.read')).toBe(false)
    await wrapper.get('[data-memory-entry]').trigger('keydown', { key: 'Enter' })
    await vi.waitFor(() => expect(request.mock.calls.some(([method]) => method === 'memory.read')).toBe(true))
    wrapper.unmount()
  })

  it('keeps plan menu activation separate from opening files and folders', async () => {
    const readFile = vi.fn(async () => ({ path: '方案/示例.md', content: '# 示例' }))
    const client = { listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries: [{ name: '示例.md', path: '方案/示例.md', folder: '', title: '示例', status: 'draft', summary: '', favorite: false, size: 1, updated_at: 0 }], folders: [{ name: '目录', path: '方案/目录', dir: '目录', parent: '', count: 0 }] })), readFile }
    const wrapper = mount(PlanLibraryView, { props: { client: client as any, projectId: 'test' } })
    await vi.waitFor(() => expect(wrapper.find('[data-library-entry]').exists()).toBe(true))
    await wrapper.get('[data-library-tab="folders"]').trigger('click')
    await wrapper.get('[data-library-folder] .card-menu-btn').trigger('keydown', { key: 'Enter' })
    expect(wrapper.find('[data-library-folder]').exists()).toBe(true)
    await wrapper.get('[data-library-tab="all"]').trigger('click')
    await wrapper.get('[data-library-entry] .card-menu-btn').trigger('keydown', { key: 'Enter' })
    expect(readFile).not.toHaveBeenCalled()
    await wrapper.get('[data-library-view-toggle] button[aria-label="列表视图"]').trigger('click')
    await wrapper.get('[data-library-entry] .card-menu-btn').trigger('keydown', { key: 'Enter' })
    expect(readFile).not.toHaveBeenCalled()
    await wrapper.get('[data-library-entry]').trigger('keydown', { key: 'Enter' })
    await vi.waitFor(() => expect(readFile).toHaveBeenCalled())
    wrapper.unmount()
  })
})
