import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { WorkflowPoliciesPanel, type WorkflowDef } from '@lamtools/bundled-workflow-ui'

function definition(policies: WorkflowDef['policies'] = {}): WorkflowDef {
  return {
    id: 'wf-policy',
    name: 'policy',
    description: '',
    nodes: [],
    edges: [],
    input_params: [],
    output_port: '',
    exposed: false,
    tool_name: '',
    work_root: 'C:/work',
    map: '',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    policies,
  }
}

describe('WorkflowPoliciesPanel', () => {
  it('writes flow-control policy into both the projection and V2 document', async () => {
    const update = vi.fn()
    const current = definition()
    current.document = {
      format: 'lamtools.workflow',
      version: 2,
      resource: { id: current.id, name: current.name, description: '', work_root: current.work_root, revision: 1, created_at: current.created_at, updated_at: current.updated_at },
      graph: { nodes: [], links: [] },
      interface: { inputs: [], outputs: [] },
      exposure: { enabled: false, tool_name: '' },
      canvas: { viewport: { x: 0, y: 0, zoom: 1 }, node_views: {}, groups: [], reroutes: [], annotations: [] },
      triggers: [],
      policies: {},
    }
    const wrapper = mount(WorkflowPoliciesPanel, {
      props: { workflowDefinition: current, onUpdateDefinition: update },
    })
    const toggles = wrapper.findAll('input[type="checkbox"]')
    await toggles[0].setValue(true)
    expect(update).toHaveBeenCalledTimes(1)
    expect(update.mock.calls[0][0]).toMatchObject({
      policies: { concurrency: { key: 'workflow', max: 1 } },
      document: { policies: { concurrency: { key: 'workflow', max: 1 } } },
    })
  })

  it('keeps queue priority signed and disables editing while running', async () => {
    const update = vi.fn()
    const wrapper = mount(WorkflowPoliciesPanel, {
      props: { workflowDefinition: definition({ priority: -2 }), onUpdateDefinition: update },
    })
    const priority = wrapper.get('input[type="number"]')
    await priority.setValue('-5')
    await priority.trigger('change')
    expect(update.mock.calls.at(-1)?.[0].policies.priority).toBe(-5)

    await wrapper.setProps({ disabled: true })
    expect(wrapper.findAll('input').every((item) => item.attributes('disabled') !== undefined)).toBe(true)
  })
})
