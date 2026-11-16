import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CoreSettings from '../src/components/CoreSettings.vue'
import CoreSuperAgentPanel from '../src/components/CoreSuperAgentPanel.vue'
import { DEFAULT_THEME } from '../src/helpers/theme'

const wrappers: VueWrapper[] = []
afterEach(() => { for (const wrapper of wrappers.splice(0)) wrapper.unmount() })

describe('shared selection in model and delegation settings', () => {
  it('saves model group membership after changing the checkbox', async () => {
    const wrapper = mount(CoreSettings, { props: {
      providers: [{ id: 'p1', name: 'Provider', api_type: 'openai', base_url: 'https://example.com', has_api_key: true }],
      models: [{ id: 'm1', provider_id: 'p1', model_id: 'model', display_name: 'Model', capability: 'multimodal' }],
      modelGroups: [{ id: 'g1', name: 'Group', model_ids: ['m1'] }], catalogView: 'group', density: 'standard', theme: structuredClone(DEFAULT_THEME),
      requestRpc: vi.fn(async () => ({})),
    }, global: { stubs: { Teleport: true } } })
    wrappers.push(wrapper)
    await flushPromises()
    await wrapper.get('[data-model-group-members]').trigger('click')
    await wrapper.get('[data-model-group-members-form] input.sunday-checkbox').setValue(false)
    await wrapper.get('[data-model-group-members-save]').trigger('click')
    expect(wrapper.emitted('set-model-group-members')).toContainEqual([{ group_id: 'g1', model_ids: [] }])
  })
  it('retains separate approval, push, and pull request permissions', async () => {
    const rpc = vi.fn(async (method: string) => method === 'superagent.goal.submit' ? { result: { status: 'accepted' } } : { tickets: [] })
    const wrapper = mount(CoreSuperAgentPanel, { props: { requestRpc: rpc, workRoot: 'C:/repo' } })
    wrappers.push(wrapper)
    await flushPromises()
    await wrapper.get('.primary-button').trigger('click')
    await wrapper.get('textarea').setValue('实现目标')
    const boxes = wrapper.findAll('input.sunday-checkbox')
    expect(boxes).toHaveLength(3)
    expect(boxes.every(box => !(box.element as HTMLInputElement).checked)).toBe(true)
    await boxes[0].setValue(true)
    await boxes[2].setValue(true)
    await wrapper.get('.sa-actions .primary-button').trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('superagent.goal.submit', expect.objectContaining({ goal: '实现目标', require_approval: true, can_push: false, can_create_pr: true }))
  })
})
