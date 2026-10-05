import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ArtifactPanel from '../src/components/ArtifactPanel.vue'
import CoreConfirmDialog from '../src/components/CoreConfirmDialog.vue'
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
  it('confirms bulk deletion in the app dialog before invoking the artifact delete RPC', async () => {
    const requestRpc = vi.fn(async (method: string) => (
      method === 'artifact.list' ? { artifacts: [artifact('a1')] } : {}
    ))
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

    // 先问一次：确认框开着、RPC 还没发。
    const dialog = wrapper.getComponent(CoreConfirmDialog)
    expect(dialog.props('open')).toBe(true)
    expect(dialog.props('title')).toBe('从成果库移除？')
    expect(requestRpc).not.toHaveBeenCalledWith('artifact.delete', expect.anything())

    // 取消不执行；确认才执行。
    dialog.vm.$emit('cancel')
    await flushPromises()
    expect(requestRpc).not.toHaveBeenCalledWith('artifact.delete', expect.anything())

    await wrapper.get('.artifact-actions .text-btn.danger').trigger('click')
    wrapper.getComponent(CoreConfirmDialog).vm.$emit('confirm')
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
              },
              {
                artifact_id: 'output-1',
                name: 'report.pdf',
                kind: 'pdf',
                role: 'deliverable',
                status: 'completed',
                source: 'agent_generated',
                path: 'workspace://report.pdf',
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
    expect(wrapper.text()).toContain('用户')
    expect(wrapper.text()).not.toContain('个版本')
    await wrapper.get('input[aria-label="搜索成果库"]').setValue('report')
    expect(wrapper.findAll('.artifact-item')).toHaveLength(1)
    await wrapper.get('.artifact-item-main').trigger('click')
    expect(openArtifact).toHaveBeenCalledWith(expect.objectContaining({ artifact_id: 'output-1' }))
    wrapper.unmount()
  })

  it('offers no version history and still refreshes on an artifact event', async () => {
    const requestRpc = vi.fn(async (method: string) => (
      method === 'artifact.list' ? { artifacts: [{ ...artifact('a1'), role: 'deliverable' }] } : {}
    ))
    const wrapper = mount(ArtifactPanel, {
      props: { projectId: 'project-a', transport: createFakeTransport(), requestRpc },
    })
    await flushPromises()

    // 成果没有历史版本：面板上不该出现任何版本入口或接口调用。
    expect(wrapper.text()).not.toContain('版本历史')
    expect(wrapper.find('.artifact-history').exists()).toBe(false)
    expect(requestRpc.mock.calls.map(([method]) => method)).not.toContain('artifact.revisions')
    expect(requestRpc.mock.calls.map(([method]) => method)).not.toContain('artifact.revision.restore')

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
        ? { artifacts: [{ ...artifact('a1'), role: 'deliverable', missing: true, deleted: true }] }
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
