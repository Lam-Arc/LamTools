import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import LibraryViewToggle from '../src/components/LibraryViewToggle.vue'
import MaterialsView from '../src/components/MaterialsView.vue'
import MemoryView from '../src/components/MemoryView.vue'
import PlanLibraryView from '../src/components/PlanLibraryView.vue'
const settle = async () => { for (let n = 0; n < 15; n++) await Promise.resolve() }
describe('library view switcher integration', () => {
  it('switches real materials, memory and plan views and preserves their storage policies', async () => {
    localStorage.clear()
    const artifact = { artifact_id: 'a', name: 'a.md', kind: 'document', mime_type: 'text/markdown', path: 'workspace://a.md', source: 'user_upload', availability: 'available', revision_count: 1 }
    const rpc = vi.fn(async (method: string) => method === 'artifact.list' ? { artifacts: [artifact] } : method === 'memory.tree' ? { entries: [{ path: 'a.md', is_dir: false, size: 1, modified: '', summary: '' }] } : { projects: [] })
    const entry = { name: 'plan.md', path: '方案/plan.md', folder: '', title: '示例', status: 'draft', summary: '', favorite: false, size: 10, updated_at: 0 }
    const client = { list: vi.fn(async () => []), listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries: [entry], folders: [] })) } as any
    const views = [
      { component: MaterialsView, props: { projectId: 'p', requestRpc: rpc, transport: { request: vi.fn() } }, selector: '[data-materials-view-toggle]', storage: '' },
      { component: MemoryView, props: { requestRpc: rpc, client, platform: 'desktop' }, selector: '[data-memory-view-toggle]', storage: 'lamtools.core.memory.view' },
      { component: PlanLibraryView, props: { client, projectId: 'p' }, selector: '[data-library-view-toggle]', storage: 'lamtools.core.library.view' },
    ]
    for (const item of views) {
      const wrapper = mount(item.component as any, { props: item.props as any }); await settle()
      if (item.component === MemoryView) { await wrapper.get('[data-memory-tier="global"]').trigger('click'); await settle() }
      expect(wrapper.findComponent(LibraryViewToggle).exists()).toBe(true)
      await wrapper.get(`${item.selector} [aria-label="列表视图"]`).trigger('click'); await settle()
      expect(wrapper.find('.library-row').exists()).toBe(true)
      if (item.storage) expect(localStorage.getItem(item.storage)).toBe('list')
      wrapper.unmount()
    }
    localStorage.clear()
  })
})
