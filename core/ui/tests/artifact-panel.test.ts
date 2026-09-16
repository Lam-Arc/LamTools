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
    expect(confirm).toHaveBeenCalledWith('确定将选中的 1 项从成果库移除？文件不会被删除。')
    expect(requestRpc).not.toHaveBeenCalledWith('artifact.delete', expect.anything())

    await wrapper.get('.artifact-actions .text-btn.danger').trigger('click')
    await flushPromises()
    expect(requestRpc).toHaveBeenCalledWith('artifact.delete', {
      project_id: 'project-a',
      artifact_ids: ['a1'],
    })
    wrapper.unmount()
  })

  it('keeps only V2 roles, exposes searchable metadata, and hands opening to StagePane', async () => {
    const openArtifact = vi.fn()
    const requestRpc = vi.fn(async (method: string) => (
      method === 'artifact.list'
        ? {
            artifacts: [
              {
                artifact_id: 'input-1',
                name: 'brief.md',
                kind: 'document',
                role: 'input',
                status: 'ready',
                source: 'user_upload',
                path: 'attachment://brief',
                revision_count: 2,
                latest_revision_id: 'r2',
              },
              {
                artifact_id: 'output-1',
                name: 'report.pdf',
                kind: 'pdf',
                role: 'deliverable',
                status: 'completed',
                source: 'agent_generated',
                path: 'workspace://report.pdf',
                revision_count: 1,
              },
              { artifact_id: 'ignored-1', name: 'trace.log', kind: 'file', role: 'evidence' },
            ],
          }
        : {}
    ))
    const wrapper = mount(ArtifactPanel, {
      props: { projectId: 'project-a', transport: createFakeTransport(), requestRpc, openArtifact },
    })
    await flushPromises()

    expect(wrapper.findAll('.artifact-item')).toHaveLength(2)
    expect(wrapper.text()).toContain('输入')
    expect(wrapper.text()).toContain('2 个版本')
    await wrapper.get('input[aria-label="搜索成果库"]').setValue('report')
    expect(wrapper.findAll('.artifact-item')).toHaveLength(1)
    await wrapper.get('.artifact-item-main').trigger('click')
    expect(openArtifact).toHaveBeenCalledWith(expect.objectContaining({ artifact_id: 'output-1' }), undefined)
    wrapper.unmount()
  })

  it('loads revision history, restores a revision, and refreshes on an artifact event', async () => {
    const requestRpc = vi.fn(async (method: string) => {
      if (method === 'artifact.list') {
        return {
          artifacts: [{
            ...artifact('a1'),
            role: 'deliverable',
            revisions: [
              { revision_id: 'r1', revision: 1, created_at: '2026-09-12T00:00:00Z', path: 'workspace://old.txt' },
              { revision_id: 'r2', revision: 2, created_at: '2026-09-13T00:00:00Z', path: 'workspace://new.txt' },
            ],
            latest_revision_id: 'r2',
            revision_count: 2,
          }],
        }
      }
      if (method === 'artifact.revisions') {
        return {
          revisions: [
            { revision_id: 'r1', revision: 1, created_at: '2026-09-12T00:00:00Z' },
            { revision_id: 'r2', revision: 2, created_at: '2026-09-13T00:00:00Z' },
            { revision_id: 'r3', revision: 3, created_at: '2026-09-14T00:00:00Z' },
          ],
        }
      }
      return {}
    })
    const wrapper = mount(ArtifactPanel, {
      props: { projectId: 'project-a', transport: createFakeTransport(), requestRpc },
    })
    await flushPromises()
    await wrapper.findAll('.artifact-icon-button')[1].trigger('click')
    expect(wrapper.find('.artifact-history').exists()).toBe(true)
    expect(wrapper.findAll('.artifact-revision')).toHaveLength(2)
    await wrapper.get('.artifact-revision-restore').trigger('click')
    await flushPromises()
    expect(requestRpc).toHaveBeenCalledWith('artifact.revision.restore', {
      project_id: 'project-a', artifact_id: 'a1', revision_id: 'r1',
    })
    expect(wrapper.findAll('.artifact-revision')).toHaveLength(3)

    const beforeRefresh = requestRpc.mock.calls.filter(([method]) => method === 'artifact.list').length
    await wrapper.setProps({ artifactSignal: { method: 'core/runItem', payload: { artifacts: [{ artifact_id: 'a1' }] } } })
    await flushPromises()
    const afterRefresh = requestRpc.mock.calls.filter(([method]) => method === 'artifact.list').length
    expect(afterRefresh).toBeGreaterThan(beforeRefresh)
    wrapper.unmount()
  })

  it('surfaces removed and missing states and restores a soft-removed item', async () => {
    const requestRpc = vi.fn(async (method: string) => (
      method === 'artifact.list'
        ? { artifacts: [{ ...artifact('a1'), role: 'deliverable', availability: 'metadata_only', deleted: true }] }
        : {}
    ))
    const wrapper = mount(ArtifactPanel, {
      props: { projectId: 'project-a', transport: createFakeTransport(), requestRpc },
    })
    await flushPromises()
    expect(wrapper.find('.artifact-state').text()).toContain('符合筛选')
    await wrapper.get('.artifact-removed-toggle').trigger('click')
    expect(wrapper.get('.artifact-status').text()).toContain('已移除')
    expect(wrapper.find('.artifact-item--missing').exists()).toBe(true)
    await wrapper.get('.artifact-icon-button--restore').trigger('click')
    await flushPromises()
    expect(requestRpc).toHaveBeenCalledWith('artifact.restore', {
      project_id: 'project-a', artifact_ids: ['a1'],
    })
    wrapper.unmount()
  })
})
