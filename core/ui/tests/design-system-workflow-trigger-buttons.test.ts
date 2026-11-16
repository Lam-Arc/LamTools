import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import WorkflowTriggersPanel from '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowTriggersPanel.vue'

const definition = { id: 'wf', name: 'workflow', description: '', nodes: [], edges: [], input_params: [], output_port: '', exposed: false, tool_name: '', work_root: '', map: '', created_at: '', updated_at: '', policies: {}, triggers: [{ id: 't', name: 'scheduled', type: 'interval', enabled: true, inputs: {}, every_seconds: 60 }] } as any

describe('workflow trigger actions', () => {
  it('adds a trigger with the same shared primary action and respects busy state', async () => {
    const update = vi.fn()
    const wrapper = mount(WorkflowTriggersPanel, { props: { workflowDefinition: definition, onUpdateDefinition: update } })
    const add = wrapper.get('[data-trigger-add]')
    expect(add.classes()).toEqual(expect.arrayContaining(['btn', 'btn--primary']))
    await add.trigger('click')
    expect(update).toHaveBeenCalledWith(expect.objectContaining({ triggers: expect.arrayContaining([expect.objectContaining({ id: 'trigger_2', type: 'manual' })]) }))
    await wrapper.setProps({ activationBusy: true })
    expect((add.element as HTMLButtonElement).disabled).toBe(true)
    wrapper.unmount()
  })
  it('uses shared primary actions while preserving saving and disabled state', async () => {
    const update = vi.fn()
    const wrapper = mount(WorkflowTriggersPanel, { props: { workflowDefinition: definition, onUpdateDefinition: update } })
    const save = wrapper.get('[data-trigger-save]')
    const activate = wrapper.get('[data-trigger-activate]')
    for (const action of [save, activate]) expect(action.classes()).toEqual(expect.arrayContaining(['btn', 'btn--primary']))
    await wrapper.get('input.sunday-checkbox').setValue(false)
    await wrapper.get('form[data-trigger-editor]').trigger('submit')
    expect(update).toHaveBeenCalledWith(expect.objectContaining({ triggers: [expect.objectContaining({ id: 't', enabled: false })] }))
    await wrapper.setProps({ activationBusy: true })
    expect((save.element as HTMLButtonElement).disabled).toBe(true)
    expect((activate.element as HTMLButtonElement).disabled).toBe(true)
    wrapper.unmount()
  })
})

