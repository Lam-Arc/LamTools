import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import LibraryConfirmDialog from '../src/components/LibraryConfirmDialog.vue'
import MemoryView from '../src/components/MemoryView.vue'
import PlanLibraryView from '../src/components/PlanLibraryView.vue'

const menu = vi.hoisted(() => ({ open: vi.fn() }))
vi.mock('@/components/context-menu/index.ts', () => ({ openContextMenu: menu.open }))
const settle = async () => { for (let n = 0; n < 15; n++) await Promise.resolve() }
const chooseDelete = async (element: ReturnType<ReturnType<typeof mount>['get']>) => {
  await element.trigger('contextmenu')
  const options = menu.open.mock.calls.at(-1)![0].items as Array<{ id: string; action?: () => void }>
  options.find(item => item.id === 'delete')!.action!()
  await settle()
}
describe('library destructive confirmations', () => {
  it('preserves the memory folder warning and deletes only after confirmation', async () => {
    menu.open.mockClear()
    const request = vi.fn(async (method: string) => method === 'memory.projects' ? { projects: [{ id: 'p', name: '项目', work_root: 'C:/project' }] } : method === 'memory.tree' ? { entries: [{ path: '目录', is_dir: true, size: 0, modified: '', summary: '' }, { path: '目录/a.md', is_dir: false, size: 1, modified: '', summary: '' }] } : {})
    const client = { list: vi.fn(async () => [{ id: 'p', name: '项目', workRoot: 'C:/project' }]) } as any
    const wrapper = mount(MemoryView, { props: { requestRpc: request, client, platform: 'desktop' } })
    await settle(); await wrapper.get('[data-memory-project="p"]').trigger('click'); await settle()
    await chooseDelete(wrapper.get('[data-memory-folder="目录"]'))
    expect(wrapper.findAllComponents(LibraryConfirmDialog).some(dialog => dialog.props('open'))).toBe(true)
    expect(wrapper.get('[data-memory-confirm]').text()).toContain('里面的条目也会一起删掉')
    expect(request).not.toHaveBeenCalledWith('memory.delete', expect.anything())
    await wrapper.get('[data-memory-confirm-delete]').trigger('click'); await settle()
    expect(request).toHaveBeenCalledWith('memory.delete', expect.objectContaining({ path: '目录' }))
    wrapper.unmount()
  })
  it('retains the plan deletion warning and cancellation', async () => {
    menu.open.mockClear()
    const entry = { name: 'plan.md', path: '方案/plan.md', folder: '', title: '示例', status: 'draft', summary: '', favorite: false, size: 10, updated_at: 0 }
    const client = { listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries: [entry], folders: [] })), deletePlanLibraryFile: vi.fn(async () => ({})) } as any
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'p' } })
    await settle(); await chooseDelete(wrapper.get('[data-library-entry]'))
    expect(wrapper.findAllComponents(LibraryConfirmDialog).some(dialog => dialog.props('open'))).toBe(true)
    expect(wrapper.get('[data-library-confirm]').text()).toContain('无法恢复')
    await wrapper.get('[data-library-confirm] .library-button:not([data-library-confirm-delete])').trigger('click')
    expect(client.deletePlanLibraryFile).not.toHaveBeenCalled()
    await chooseDelete(wrapper.get('[data-library-entry]'))
    await wrapper.get('[data-library-confirm-delete]').trigger('click'); await settle()
    expect(client.deletePlanLibraryFile).toHaveBeenCalledWith('p', entry.path)
    wrapper.unmount()
  })
})
