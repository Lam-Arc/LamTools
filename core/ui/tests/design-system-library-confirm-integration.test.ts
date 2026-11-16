import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MaterialsView from '../src/components/MaterialsView.vue'
import LibraryConfirmDialog from '../src/components/LibraryConfirmDialog.vue'

const settle = async () => { for (let n = 0; n < 15; n++) await Promise.resolve() }
describe('library confirmation integration', () => {
  it('confirms removal with the shared dialog and retains the warning and cancellation', async () => {
    const rpc = vi.fn(async (method: string) => method === 'artifact.list' ? { artifacts: [{ artifact_id: 'a', name: 'a.md', kind: 'document', mime_type: 'text/markdown', path: 'workspace://a.md', source: 'user_upload', availability: 'available', revision_count: 1 }] } : {})
    const wrapper = mount(MaterialsView, { props: { projectId: 'p', requestRpc: rpc, transport: { request: vi.fn() } as any } })
    await settle()
    await wrapper.get('[data-material-check="a"]').trigger('click')
    await wrapper.get('[data-materials-remove-selected]').trigger('click')
    expect(wrapper.findComponent(LibraryConfirmDialog).exists()).toBe(true)
    expect(wrapper.get('[data-materials-confirm]').text()).toContain('文件本身不会被删除')
    expect(rpc).not.toHaveBeenCalledWith('artifact.delete', expect.anything())
    await wrapper.get('[data-materials-confirm-remove]').trigger('click')
    await settle()
    expect(rpc).toHaveBeenCalledWith('artifact.delete', expect.objectContaining({ project_id: 'p', artifact_ids: ['a'] }))
    wrapper.unmount()
  })
})
