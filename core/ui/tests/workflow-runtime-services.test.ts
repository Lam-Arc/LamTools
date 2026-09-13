import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  buildWorkflowQueueClearPayload,
  buildWorkflowQueuePayload,
  createWorkflowApi,
  normalizeWorkflowObjectInfo,
  normalizeWorkflowQueueItem,
  normalizeImportedWorkflow,
  schemaFields,
  schemaPorts,
  WorkflowNodeCatalog,
  WorkflowRunInputForm,
  WorkflowQueuePanel,
  WorkflowResourcesPanel,
} from '@lamtools/bundled-workflow-ui'

describe('workflow runtime service contracts', () => {
  beforeEach(() => localStorage.clear())

  it('reads ComfyUI-style schema fields and derives ports without dropping explicit ports', () => {
    const schema = {
      name: 'demo', display_name: 'Demo', category: 'workflow/test',
      input: { required: { prompt: ['STRING', { multiline: true }] }, optional: { count: ['INT', { default: 2 }] } },
      output: { answer: { type: 'STRING' } },
    }
    expect(schemaFields(schema, 'input')).toMatchObject([
      { name: 'prompt', type: 'string', required: true, multiline: true },
      { name: 'count', type: 'number', required: false, default: 2 },
    ])
    expect(schemaPorts(schema, [{ name: 'prompt', type: 'string', direction: 'in', description: 'keep' }])).toMatchObject([
      { name: 'prompt', direction: 'in', description: 'keep' },
      { name: 'count', type: 'number', direction: 'in' },
      { name: 'answer', type: 'string', direction: 'out' },
    ])
  })

  it('normalizes object-info envelopes and maps queue RPCs to CLI wire names', async () => {
    const rpc = vi.fn()
      .mockResolvedValueOnce({ object_info: { demo: { name: 'demo', display_name: 'Demo', input: {}, output: {} } } })
      .mockResolvedValueOnce({ queue: { queue_id: 'q1', run_id: 'r1', workflow_name: 'demo', status: 'queued', inputs: { prompt: 'hi' } } })
      .mockResolvedValueOnce({ queue: [{ queue_id: 'q1', run_id: 'r1', workflow_name: 'demo', status: 'queued' }] })
      .mockResolvedValueOnce({ history: [{ queue_id: 'q0', run_id: 'r0', workflow_name: 'demo', status: 'completed', result: { status: 'completed', cache: { n: { status: 'hit', key: 'k' } } } }] })
      .mockResolvedValueOnce({ queue: { queue_id: 'q1', run_id: 'r1', workflow_name: 'demo', status: 'running' } })
      .mockResolvedValueOnce({ count: 1, cleared: 1 })
      .mockResolvedValueOnce({ queue: { queue_id: 'q1', run_id: 'r1', workflow_name: 'demo', status: 'cancelled' } })
    const api = createWorkflowApi(rpc)
    await expect(api.objectInfo()).resolves.toMatchObject({ demo: { name: 'demo', display_name: 'Demo' } })
    await expect(api.enqueue('demo', { workRoot: 'C:/work', inputs: { prompt: 'hi' }, maxSteps: 2 })).resolves.toMatchObject({ queue_id: 'q1', inputs: { prompt: 'hi' } })
    await expect(api.listQueue({ name: 'demo' })).resolves.toHaveLength(1)
    await expect(api.historyQueue({ name: 'demo' })).resolves.toMatchObject([{ result: { cache: { n: { status: 'hit', key: 'k' } } } }])
    await expect(api.getQueue('q1')).resolves.toMatchObject({ status: 'running' })
    await expect(api.clearQueue({ confirm: true, all: false, name: 'demo' })).resolves.toBe(1)
    await expect(api.cancelQueue('q1')).resolves.toMatchObject({ status: 'cancelled' })
    expect(rpc.mock.calls.map(([method]) => method)).toEqual([
      'workflow.object_info', 'workflow.queue.enqueue', 'workflow.queue.list', 'workflow.queue.history', 'workflow.queue.get', 'workflow.queue.clear', 'workflow.queue.cancel',
    ])
    expect(rpc.mock.calls[1][1]).toMatchObject({ name: 'demo', work_root: 'C:/work', inputs: { prompt: 'hi' }, max_steps: 2 })
    expect(rpc.mock.calls[5][1]).toMatchObject({ confirm: true, name: 'demo' })
  })

  it('keeps queue and clear payloads explicit for dangerous operations', () => {
    expect(buildWorkflowQueuePayload('demo', { inputs: { x: 1 }, threadId: 't', runId: 'r' })).toMatchObject({ name: 'demo', inputs: { x: 1 }, thread_id: 't', run_id: 'r' })
    expect(buildWorkflowQueueClearPayload({ confirm: false, all: true })).toEqual({ confirm: false, all: true })
    expect(normalizeWorkflowObjectInfo({ node_types: { ai: { title: 'AI', input: {}, output: {} } } })).toMatchObject({ ai: { name: 'ai', title: 'AI' } })
    expect(normalizeWorkflowQueueItem({ queueId: 'q', runId: 'r', status: 'unknown' })).toMatchObject({ queue_id: 'q', id: 'q', run_id: 'r', status: 'queued' })
  })

  it('supports legacy workflow JSON aliases and wrappers', () => {
    const workflow = normalizeImportedWorkflow({ workflow: {
      workflow_id: 'legacy-1', workflow_name: '旧工作流', inputParams: { prompt: { type: 'string', required: true } },
      nodes: { a: { type: 'action', config: { action_type: 'script', script: 'out = prompt' }, inputs: { prompt: 'string' }, outputs: { out: 'string' }, x: 8, y: 12 } },
      connections: [{ from: 'a', from_port: 'out', to: 'a', to_port: 'prompt' }],
    } })
    expect(workflow).toMatchObject({ id: 'legacy-1', name: '旧工作流', input_params: [{ name: 'prompt', required: true }], nodes: [{ id: 'a', kind: 'script', position: { x: 8, y: 12 } }] })
    expect(workflow.nodes[0].ports).toMatchObject([{ name: 'prompt', direction: 'in' }, { name: 'out', direction: 'out' }])
  })

  it('passes ComfyUI import/export through the backend without projecting it to map', async () => {
    const comfy = {
      version: 1,
      last_node_id: 7,
      last_link_id: 11,
      nodes: [{ id: 7, type: 'ThirdPartyNode', pos: [12, 34], size: [260, 140], inputs: [], outputs: [], widgets_values: ['keep-me'], properties: { vendor: { untouched: true } } }],
      links: [],
      groups: [{ title: 'group', bounding: [0, 0, 300, 200] }],
      reroutes: [{ id: 3, pos: [40, 50] }],
      extra: { ds: { scale: 0.75, offset: [18, 24] }, vendor_extension: { exact: true } },
    }
    const rpc = vi.fn()
      .mockResolvedValueOnce({ document: {
        format: 'lamtools.workflow', version: 2,
        resource: { id: 'wf-comfy', name: 'comfy-import', description: '', work_root: 'C:/work', revision: 1, created_at: '', updated_at: '' },
        graph: { nodes: [], links: [] }, interface: { inputs: [], outputs: [] }, exposure: { enabled: false, tool_name: '' },
        canvas: { viewport: { x: 18, y: 24, zoom: 0.75 }, node_views: {}, groups: [], reroutes: [], annotations: [] },
      } })
      .mockResolvedValueOnce({ workflow: comfy })
    const api = createWorkflowApi(rpc)
    await api.importComfyUi(comfy, 'comfy-import', 'C:/work', 0)
    await expect(api.exportComfyUi('comfy-import', '0.4', 'C:/work')).resolves.toEqual(comfy)
    expect(rpc.mock.calls[0]).toEqual(['workflow.import.comfyui', {
      name: 'comfy-import', workflow: comfy, work_root: 'C:/work', expected_revision: 0,
    }])
    expect(rpc.mock.calls[1]).toEqual(['workflow.export.comfyui', {
      name: 'comfy-import', version: '0.4', work_root: 'C:/work',
    }])
  })
})

describe('workflow runtime service interactions', () => {
  it('adds a catalog node from a keyboard-activated entry and persists recent/favorite state', async () => {
    const add = vi.fn()
    const wrapper = mount(WorkflowNodeCatalog, {
      props: { schemas: { ai: { name: 'ai', display_name: 'AI', category: 'workflow/ai', input: {}, output: {} } }, onAdd: add },
    })
    await wrapper.get('.wf-catalog-add').trigger('keydown.enter')
    expect(add).toHaveBeenCalledWith(expect.objectContaining({ name: 'ai' }))
    await wrapper.get('.wf-catalog-favorite').trigger('click')
    expect(JSON.parse(localStorage.getItem('lamtools.workflow.node-catalog.v1') || '{}').favorites).toEqual(['ai'])
    wrapper.unmount()
  })

  it('validates required run inputs and emits typed values', async () => {
    const submit = vi.fn()
    const wrapper = mount(WorkflowRunInputForm, {
      props: { params: [
        { name: 'prompt', type: 'string', required: true },
        { name: 'count', type: 'number', required: true },
        { name: 'options', type: 'object', required: false, default: {} },
      ], onSubmit: submit },
    })
    await wrapper.get('form').trigger('submit')
    expect(wrapper.text()).toContain('请填写必填输入：prompt')
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('hello')
    await inputs[1].setValue('3')
    await wrapper.get('form').trigger('submit')
    expect(submit).toHaveBeenCalledWith({ prompt: 'hello', count: 3, options: {} })
    wrapper.unmount()
  })

  it('requires a second confirmation before clearing queue history', async () => {
    const clear = vi.fn()
    const wrapper = mount(WorkflowQueuePanel, {
      props: { history: [{ queue_id: 'q1', id: 'q1', workflow_id: 'w', workflow_name: 'demo', work_root: '', thread_id: 't', run_id: 'r', inputs: {}, status: 'completed' }], onClear: clear },
    })
    await wrapper.get('.wf-queue-danger').trigger('click')
    expect(clear).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('此操作不可撤销')
    await wrapper.get('.wf-queue-confirm .wf-queue-danger').trigger('click')
    expect(clear).toHaveBeenCalledWith(false)
    wrapper.unmount()
  })

  it('preserves raw ComfyUI JSON at the resource boundary and exposes all export formats', async () => {
    const imported = vi.fn()
    const exported = vi.fn().mockResolvedValue(true)
    const workflow = {
      id: 'wf', name: 'demo', description: '', nodes: [], edges: [], input_params: [], output_port: '',
      exposed: false, tool_name: '', work_root: '', map: '', created_at: '', updated_at: '',
    }
    const wrapper = mount(WorkflowResourcesPanel, { props: { workflow, onImport: imported, onExport: exported } })
    const comfy = {
      version: 1, last_node_id: 1, last_link_id: 0,
      nodes: [{ id: 1, type: 'VendorNode', pos: [10, 20], inputs: [], outputs: [], widgets_values: [{ exact: true }] }],
      links: [], extra: { vendor: { preserve: ['all', 'fields'] } },
    }
    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    Object.defineProperty(input, 'files', {
      configurable: true,
      value: [new File([JSON.stringify(comfy)], 'vendor.json', { type: 'application/json' })],
    })
    await wrapper.get('input[type="file"]').trigger('change')
    await flushPromises()
    expect(imported).toHaveBeenCalledWith({ kind: 'comfyui', name: 'vendor', version: '1', workflow: comfy })

    const buttons = wrapper.findAll('.wf-resource-actions button')
    await buttons[1].trigger('click')
    await buttons[2].trigger('click')
    await buttons[3].trigger('click')
    expect(exported.mock.calls.map(([format]) => format)).toEqual(['native-v2', 'comfyui-v1', 'comfyui-v0.4'])
    wrapper.unmount()
  })
})
