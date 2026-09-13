import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  createWorkflowNodeFromSchema,
  deleteWorkflowCanvasElementContents,
  workflowCanvasElementContents,
  WorkflowNodeCatalog,
} from '@lamtools/bundled-workflow-ui'

describe('workflow schema-driven node contract', () => {
  beforeEach(() => localStorage.clear())

  it('keeps registry type ids when creating first-class and custom nodes', () => {
    const model = createWorkflowNodeFromSchema({
      name: 'model', display_name: 'Model', category: 'workflow/model',
      input: { required: { prompt: { type: 'string' } } },
      output: { output: { type: 'string' } },
    }, 'model-1', { x: 10, y: 20 })
    const custom = createWorkflowNodeFromSchema({
      name: 'vendor.echo', display_name: 'Vendor Echo', category: 'vendor/test',
      input: { required: { value: { type: 'string' } } },
      output: { out: { type: 'string' } },
    }, 'echo-1', { x: 30, y: 40 })

    expect(model).toMatchObject({ kind: 'model', type_id: 'model', title: 'Model' })
    expect(model.ports).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'prompt', direction: 'in', type: 'string' }),
      expect.objectContaining({ name: 'output', direction: 'out', type: 'string' }),
    ]))
    expect(custom).toMatchObject({ kind: 'vendor.echo', type_id: 'vendor.echo', title: 'Vendor Echo' })
    expect(custom.ports).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'value', direction: 'in', type: 'string' }),
      expect.objectContaining({ name: 'out', direction: 'out', type: 'string' }),
    ]))
  })

  it('keeps legacy aliases loadable but hides them from the default add catalog', async () => {
    const add = () => undefined
    const wrapper = mount(WorkflowNodeCatalog, {
      props: {
        schemas: {
          model: { name: 'model', display_name: 'Model', category: 'workflow/model', input: {}, output: {} },
          agent: { name: 'agent', display_name: 'Agent', category: 'workflow/agent', input: {}, output: {} },
          ai: { name: 'ai', display_name: 'AI (legacy)', category: 'workflow/legacy', hidden: true, legacy: true, input: {}, output: {} },
          script: { name: 'script', display_name: 'Script (legacy)', category: 'workflow/legacy', hidden: true, legacy: true, input: {}, output: {} },
          custom: { name: 'vendor.echo', display_name: 'Vendor Echo', category: 'vendor/test', input: {}, output: {} },
        },
        onAdd: add,
      },
    })
    expect(wrapper.text()).toContain('Model')
    expect(wrapper.text()).toContain('Agent')
    expect(wrapper.text()).toContain('Vendor Echo')
    expect(wrapper.text()).not.toContain('AI (legacy)')
    expect(wrapper.text()).not.toContain('Script (legacy)')
    wrapper.unmount()
  })

  it('treats frame/group membership as a visual container contract', () => {
    const definition = {
      nodes: [
        { id: 'inside', kind: 'model', title: 'inside', config: {}, ports: [], position: { x: 20, y: 30 } },
        { id: 'outside', kind: 'model', title: 'outside', config: {}, ports: [], position: { x: 700, y: 700 } },
      ],
      edges: [{ id: 'link', source: 'inside', source_port: 'out', target: 'outside', target_port: 'in' }],
      canvas_elements: [
        { id: 'frame', kind: 'frame', title: 'Frame', text: '', position: { x: 0, y: 0 }, width: 300, height: 240 },
        { id: 'note', kind: 'note', title: 'Note', text: '', position: { x: 20, y: 40 }, width: 120, height: 80, parent_id: 'frame' },
      ],
    } as any
    expect(workflowCanvasElementContents(definition, 'frame')).toMatchObject({
      nodeIds: ['inside'], canvasElementIds: ['note'],
    })
    expect(deleteWorkflowCanvasElementContents(definition, 'frame')).toMatchObject({
      deletedNodeIds: ['inside'], deletedCanvasElementIds: ['frame', 'note'],
      nodes: [{ id: 'outside' }], edges: [], canvas_elements: [],
    })
  })
})
