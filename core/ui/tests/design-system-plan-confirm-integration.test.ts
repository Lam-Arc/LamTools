import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PlanLibraryView from '../src/components/PlanLibraryView.vue'
import LibraryConfirmDialog from '../src/components/LibraryConfirmDialog.vue'
const settle = async () => { for (let n = 0; n < 15; n++) await Promise.resolve() }
describe('plan library confirmation integration', () => {
  it('preserves unsaved changes when cancelling and discards only after confirmation', async () => {
    const entry = { name: 'plan.md', path: '方案/plan.md', folder: '', title: '示例', status: 'draft', summary: '', favorite: false, size: 10, updated_at: 0 }
    const client = { listPlanLibrary: vi.fn(async () => ({ dir: '方案', entries: [entry], folders: [] })), readFile: vi.fn(async () => ({ path: entry.path, content: '# 示例' })), writeFile: vi.fn() } as any
    const wrapper = mount(PlanLibraryView, { props: { client, projectId: 'p' } })
    await settle()
    await wrapper.get('[data-library-entry]').trigger('click'); await settle()
    await wrapper.findAll('.full-area-actions button').find(button => button.text() === '编辑')!.trigger('click'); await settle()
    await wrapper.get('[data-library-editor-input]').setValue('未保存'); await settle()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await settle()
    expect(wrapper.findAllComponents(LibraryConfirmDialog).some(dialog => dialog.props('open'))).toBe(true)
    expect(wrapper.get('[data-library-discard]').text()).toContain('还有没保存的内容')
    await wrapper.findAll('.dialog-actions button').find(button => button.text() === '继续编辑')!.trigger('click'); await settle()
    expect((wrapper.get('[data-library-editor-input]').element as HTMLTextAreaElement).value).toBe('未保存')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await settle()
    await wrapper.get('[data-library-discard-confirm]').trigger('click'); await settle()
    expect(wrapper.find('[data-library-editor]').exists()).toBe(false)
    expect(client.writeFile).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
