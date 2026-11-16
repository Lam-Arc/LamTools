import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import LibraryConfirmDialog from '../src/components/LibraryConfirmDialog.vue'
import MemoryView from '../src/components/MemoryView.vue'
const settle = async () => { for (let n = 0; n < 15; n++) await Promise.resolve() }
describe('memory unsaved confirmation', () => {
  it('keeps edits after cancellation and discards without writing', async () => {
    const request = vi.fn(async (method: string) => method === 'memory.projects' ? { projects: [{ id: 'p', name: '项目', work_root: 'C:/project' }] } : method === 'memory.tree' ? { entries: [{ path: 'a.md', is_dir: false, size: 1, modified: '', summary: '' }] } : method === 'memory.read' ? { path: 'a.md', content: '# 旧内容' } : {})
    const client = { list: vi.fn(async () => [{ id: 'p', name: '项目', workRoot: 'C:/project' }]) } as any
    const wrapper = mount(MemoryView, { props: { requestRpc: request, client, platform: 'desktop' } })
    await settle(); await wrapper.get('[data-memory-project="p"]').trigger('click'); await settle()
    await wrapper.get('[data-memory-entry]').trigger('click'); await settle()
    await wrapper.get('.full-area-actions button').trigger('click'); await settle()
    await wrapper.get('[data-memory-editor-input]').setValue('未保存'); await settle()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await settle()
    expect(wrapper.findAllComponents(LibraryConfirmDialog).some(dialog => dialog.props('open'))).toBe(true)
    expect(wrapper.get('[data-memory-discard]').text()).toContain('还有没保存的内容')
    await wrapper.findAll('.dialog-actions button').find(button => button.text() === '继续编辑')!.trigger('click'); await settle()
    expect((wrapper.get('[data-memory-editor-input]').element as HTMLTextAreaElement).value).toBe('未保存')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await settle()
    await wrapper.get('[data-memory-discard-confirm]').trigger('click'); await settle()
    expect(wrapper.find('[data-memory-editor]').exists()).toBe(false)
    expect(request).not.toHaveBeenCalledWith('memory.write', expect.anything())
    wrapper.unmount()
  })
})
