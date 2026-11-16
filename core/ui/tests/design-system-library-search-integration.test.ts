import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MaterialsView from '../src/components/MaterialsView.vue'
import MemoryView from '../src/components/MemoryView.vue'
import PlanLibraryView from '../src/components/PlanLibraryView.vue'
import LibrarySearchField from '../src/components/LibrarySearchField.vue'
const settle = async () => { for (let n = 0; n < 15; n++) await Promise.resolve() }
describe('library search integration', () => {
  it('filters real materials, memory and plans while preserving contextual labels', async () => {
    const artifacts = ['apple', 'banana'].map(name => ({ artifact_id: name, name: `${name}.md`, kind: 'document', mime_type: 'text/markdown', path: `workspace://${name}.md`, source: 'user_upload', availability: 'available', revision_count: 1 }))
    const memory = ['apple', 'banana'].map(name => ({ path: `${name}.md`, is_dir: false, size: 1, modified: '', summary: '' }))
    const entries = ['apple', 'banana'].map(name => ({ name: `${name}.md`, path: `方案/${name}.md`, folder: '', title: name, status: 'draft', summary: '', favorite: false, size: 1, updated_at: 0 }))
    const rpc = vi.fn(async (method: string) => method === 'artifact.list' ? { artifacts } : method === 'memory.tree' ? { entries: memory } : { projects: [] })
    const client = { list: vi.fn(async () => []), listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries, folders: [] })) } as any
    const views = [
      { component: MaterialsView, props: { projectId: 'p', requestRpc: rpc, transport: { request: vi.fn() } }, search: '[data-materials-search]', result: '[data-material]' },
      { component: MemoryView, props: { requestRpc: rpc, client, platform: 'desktop' }, search: '[data-memory-search]', result: '[data-memory-entry]' },
      { component: PlanLibraryView, props: { client, projectId: 'p' }, search: '[data-library-search]', result: '[data-library-entry]' },
    ]
    for (const item of views) {
      const wrapper = mount(item.component as any, { props: item.props as any }); await settle()
      if (item.component === MemoryView) {
        expect(wrapper.get(item.search).attributes('aria-label')).toBe('搜索项目')
        await wrapper.get('[data-memory-tier="global"]').trigger('click'); await settle()
        expect(wrapper.get(item.search).attributes('aria-label')).toBe('搜索记忆')
      }
      expect(wrapper.findComponent(LibrarySearchField).exists()).toBe(true)
      expect(wrapper.findAll(item.result)).toHaveLength(2)
      await wrapper.get(item.search).setValue('apple'); await settle()
      expect(wrapper.findAll(item.result)).toHaveLength(1)
      expect(wrapper.get(item.result).text().toLowerCase()).toContain('apple')
      wrapper.unmount()
    }
  })
})
