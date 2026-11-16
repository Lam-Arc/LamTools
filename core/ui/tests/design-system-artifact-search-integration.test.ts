import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ArtifactPanel from '../src/components/ArtifactPanel.vue'
import LibrarySearchField from '../src/components/LibrarySearchField.vue'

describe('artifact search composition', () => {
  it('filters and clears using the shared search field', async () => {
    const requestRpc = vi.fn(async () => ({ artifacts: [
      { artifact_id: 'a', name: 'report.pdf', kind: 'pdf', role: 'deliverable', status: 'completed', source: 'agent_generated', path: 'workspace://report.pdf' },
      { artifact_id: 'b', name: 'notes.txt', kind: 'file', role: 'input', status: 'ready', source: 'user_upload', path: 'workspace://notes.txt' },
    ] }))
    const wrapper = mount(ArtifactPanel, { props: { projectId: 'p', requestRpc } })
    await flushPromises()
    expect(wrapper.findComponent(LibrarySearchField).exists()).toBe(true)
    expect(wrapper.findAll('.artifact-item')).toHaveLength(2)
    await wrapper.get('input[aria-label="搜索成果库"]').setValue('report')
    expect(wrapper.findAll('.artifact-item')).toHaveLength(1)
    await wrapper.get('button[aria-label="清除搜索"]').trigger('click')
    expect(wrapper.findAll('.artifact-item')).toHaveLength(2)
    expect((wrapper.get('input[aria-label="搜索成果库"]').element as HTMLInputElement).value).toBe('')
    wrapper.unmount()
  })
})
