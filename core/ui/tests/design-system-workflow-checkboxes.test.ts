import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SchemaNodeEditor from '../../src/lamtools_core/plugins/bundled/workflow/ui/SchemaNodeEditor.vue'
import WorkflowRunInputForm from '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowRunInputForm.vue'
import WorkflowPoliciesPanel from '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowPoliciesPanel.vue'
import WorkflowTriggersPanel from '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowTriggersPanel.vue'

const definition = { id: 'wf', name: 'workflow', description: '', nodes: [], edges: [], input_params: [], output_port: '', exposed: false, tool_name: '', work_root: '', map: '', created_at: '', updated_at: '', policies: {}, triggers: [{ id: 't', name: 'manual', type: 'manual', enabled: true, inputs: {} }] } as any

describe('shared workflow checkboxes', () => {
  it('retains typed schema boolean updates', async () => {
    const schema = { name: 'sample', type_id: 'sample', input: { required: { enabled: { type: 'boolean' } } } } as any
    const wrapper = mount(SchemaNodeEditor, { props: { schema, modelValue: { enabled: false }, ports: [] } })
    await wrapper.get('input.sunday-checkbox').setValue(true)
    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({ enabled: true })
    wrapper.unmount()
  })
  it('submits workflow run input as a boolean', async () => {
    const wrapper = mount(WorkflowRunInputForm, { props: { params: [{ name: 'enabled', type: 'boolean' }] } })
    await wrapper.get('input.sunday-checkbox').setValue(true)
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toEqual({ enabled: true })
    wrapper.unmount()
  })
  it('updates policies and honors disabled state', async () => {
    const update = vi.fn()
    const wrapper = mount(WorkflowPoliciesPanel, { props: { workflowDefinition: definition, onUpdateDefinition: update } })
    const boxes = wrapper.findAll('input.sunday-checkbox')
    expect(boxes).toHaveLength(4)
    await boxes[0].setValue(true)
    expect(update).toHaveBeenCalledWith(expect.objectContaining({ policies: { concurrency: { key: 'workflow', max: 1 } } }))
    await wrapper.setProps({ disabled: true })
    expect(boxes.every(box => (box.element as HTMLInputElement).disabled)).toBe(true)
    wrapper.unmount()
  })
  it('retains trigger enabled draft and saves it', async () => {
    const update = vi.fn()
    const wrapper = mount(WorkflowTriggersPanel, { props: { workflowDefinition: definition, onUpdateDefinition: update } })
    await wrapper.get('input.sunday-checkbox').setValue(false)
    await wrapper.get('form[data-trigger-editor]').trigger('submit')
    expect(update).toHaveBeenCalledWith(expect.objectContaining({ triggers: [expect.objectContaining({ id: 't', enabled: false })] }))
    wrapper.unmount()
  })
})
