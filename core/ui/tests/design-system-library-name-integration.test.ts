import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import LibraryNameDialog from '../src/components/LibraryNameDialog.vue'
import MemoryView from '../src/components/MemoryView.vue'
import PlanLibraryView from '../src/components/PlanLibraryView.vue'
const settle = async () => { for (let n = 0; n < 15; n++) await Promise.resolve() }
describe('library name forms integration', () => {
  it('creates a memory folder and shows validation without writing invalid names', async () => {
    const request = vi.fn(async (method: string) => method === 'memory.projects' ? { projects: [{ id: 'p', name: '项目', work_root: 'C:/project' }] } : method === 'memory.tree' ? { entries: [] } : {})
    const client = { list: vi.fn(async () => [{ id: 'p', name: '项目', workRoot: 'C:/project' }]) } as any
    const wrapper = mount(MemoryView, { props: { requestRpc: request, client, platform: 'desktop' } })
    await settle(); await wrapper.get('[data-memory-project="p"]').trigger('click'); await settle()
    await wrapper.get('[data-memory-create-folder]').trigger('click')
    expect(wrapper.findComponent(LibraryNameDialog).exists()).toBe(true)
    const input = wrapper.get('[data-memory-dialog-input="create-folder"]')
    await input.setValue('bad/name'); await wrapper.get('[data-memory-dialog-submit]').trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('名称不能包含路径分隔符')
    expect(request).not.toHaveBeenCalledWith('memory.mkdir', expect.anything())
    await input.setValue('笔记'); await wrapper.get('[data-memory-dialog-submit]').trigger('click'); await settle()
    expect(request).toHaveBeenCalledWith('memory.mkdir', expect.objectContaining({ path: '笔记' }))
    wrapper.unmount()
  })
  it('creates a plan folder with the current name and preserves errors', async () => {
    const create = vi.fn().mockRejectedValueOnce(new Error('创建失败')).mockResolvedValueOnce({})
    const client = { listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries: [], folders: [] })), createPlanLibraryFolder: create } as any
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'p' } })
    await settle(); await wrapper.get('[data-library-create-folder]').trigger('click')
    expect(wrapper.findComponent(LibraryNameDialog).exists()).toBe(true)
    await wrapper.get('[data-library-dialog-input="create-folder"]').setValue('计划')
    await wrapper.get('[data-library-dialog-submit]').trigger('click'); await settle()
    expect(wrapper.get('[role="alert"]').text()).toBe('创建失败')
    await wrapper.get('[data-library-dialog-submit]').trigger('click'); await settle()
    expect(create).toHaveBeenLastCalledWith('p', '计划')
    expect(wrapper.find('[data-library-dialog]').exists()).toBe(false)
    wrapper.unmount()
  })
})
