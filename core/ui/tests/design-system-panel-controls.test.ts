import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PluginRegionBlocks from '../src/components/PluginRegionBlocks.vue'
import RightSidebarLayoutEditor from '../src/components/RightSidebarLayoutEditor.vue'
import ArtifactPanel from '../src/components/ArtifactPanel.vue'
import { createFakeTransport } from './fake-transport'

describe('shared controls in existing panels', () => {
  it('preserves plugin progress value and submits boolean action parameters', async () => {
    const rpc = vi.fn(async () => ({}))
    const regions = [{ plugin: 'demo', region: 'main', order: 0, blocks: [{ type: 'progress', label: '进度', value: 25, max: 100 }], actions: [{ id: 'run', title: '运行', operation: 'demo.run', input_schema: { properties: { enabled: { type: 'boolean', title: '启用' } } } }] }] as any
    const wrapper = mount(PluginRegionBlocks, { props: { regions, requestRpc: rpc } })
    const progress = wrapper.get('[role="progressbar"].sunday-progress')
    expect(progress.attributes('aria-valuenow')).toBe('25')
    expect(progress.get('.sunday-progress__fill').attributes('style')).toContain('25%')
    await wrapper.get('[data-action="run"]').trigger('click')
    await wrapper.get('input.sunday-checkbox').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('demo.run', { enabled: true })
    wrapper.unmount()
  })
  it('preserves sidebar visibility events and area-specific text color', async () => {
    const wrapper = mount(RightSidebarLayoutEditor, { props: { modules: [{ id: 'm', title: '模块' }], layout: { visible: { m: true } } as any } })
    const box = wrapper.get('input.sunday-checkbox')
    await box.setValue(false)
    expect(wrapper.emitted('toggle-visible')?.[0]).toEqual(['m', false])
    wrapper.unmount()
  })
  it('keeps artifact bulk selection and confirmation', async () => {
    const rpc = vi.fn(async (method: string) => method === 'artifact.list' ? { artifacts: [{ artifact_id: 'a', kind: 'document', mime_type: 'text/plain', name: 'a.txt', path: 'workspace://a', source: 'agent_generated', parent_ids: [], children_ids: [], created_at: '2026-09-13T00:00:00Z', deleted: false }] } : {})
    const wrapper = mount(ArtifactPanel, { props: { projectId: 'p', transport: createFakeTransport(), requestRpc: rpc } })
    await flushPromises()
    await wrapper.get('.btn--danger').trigger('click')
    await wrapper.get('input.sunday-checkbox').setValue(true)
    expect(wrapper.text()).toContain('1')
    await wrapper.get('.artifact-actions .btn--danger').trigger('click')
    expect(wrapper.text()).toContain('从成果库移除')
    wrapper.unmount()
  })
})
