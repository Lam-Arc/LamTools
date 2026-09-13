import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ArtifactPanel from '../src/components/ArtifactPanel.vue'
import { createFakeTransport } from './fake-transport'

function artifact(id: string) {
  return {
    artifact_id: id,
    kind: 'document',
    mime_type: 'text/plain',
    name: `${id}.txt`,
    path: `workspace://${id}.txt`,
    source: 'agent_generated',
    parent_ids: [],
    children_ids: [],
    created_at: '2026-09-13T00:00:00Z',
    deleted: false,
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ArtifactPanel', () => {
  it('confirms bulk deletion before invoking the artifact delete RPC', async () => {
    const requestRpc = vi.fn(async (method: string) => (
      method === 'artifact.list' ? { artifacts: [artifact('a1')] } : {}
    ))
    const confirm = vi.spyOn(window, 'confirm')
      .mockReturnValueOnce(false)
      .mockReturnValue(true)
    const wrapper = mount(ArtifactPanel, {
      props: {
        projectId: 'project-a',
        transport: createFakeTransport(),
        requestRpc,
      },
    })
    await flushPromises()
    requestRpc.mockClear()

    await wrapper.get('.text-btn.danger').trigger('click')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('.artifact-actions .text-btn.danger').trigger('click')
    expect(confirm).toHaveBeenCalledWith('确定删除选中的 1 个 Artifact？')
    expect(requestRpc).not.toHaveBeenCalledWith('artifact.delete', expect.anything())

    await wrapper.get('.artifact-actions .text-btn.danger').trigger('click')
    await flushPromises()
    expect(requestRpc).toHaveBeenCalledWith('artifact.delete', {
      project_id: 'project-a',
      artifact_ids: ['a1'],
    })
    wrapper.unmount()
  })
})
