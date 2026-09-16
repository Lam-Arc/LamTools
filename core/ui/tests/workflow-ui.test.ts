import { describe, expect, it, vi } from 'vitest'
import {
  buildWorkflowRunPayload,
  createWorkflowApi,
  normalizeWorkflowRunResponse,
  isWorkflowRevisionConflict,
  createWorkflowDocument,
  workflowDefinitionToDocument,
  workflowDocumentToDefinition,
  normalizeWorkflowActivations,
  reconcileWorkflowNodePorts,
  normalizeNodeStateStatus,
  normalizeWorkflowRunStatus,
  normalizeImportedWorkflow,
  serializeWorkflowJson,
  type WorkflowDef,
  type WorkflowNode,
} from '@lamtools/bundled-workflow-ui'

function node(id: string, ports: WorkflowNode['ports']): WorkflowNode {
  return { id, kind: 'command', title: id, config: { command: '' }, ports, position: { x: 0, y: 0 } }
}

function definition(overrides: Partial<WorkflowDef> = {}): WorkflowDef {
  return {
    id: 'wf-1', name: 'demo', description: '',
    nodes: [
      node('a', [{ name: 'in', type: 'string', direction: 'in' }, { name: 'out', type: 'string', direction: 'out' }]),
      node('b', [{ name: 'in', type: 'string', direction: 'in' }]),
    ],
    edges: [{ id: 'e1', source: 'a', source_port: 'out', target: 'b', target_port: 'in' }],
    input_params: [], output_port: 'b.in', exposed: false, tool_name: '', work_root: '', map: '',
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', revision: 1,
    ...overrides,
  }
}

describe('workflow status and structured run compatibility', () => {
  it('normalizes completed/failed and done/error aliases', () => {
    expect(normalizeNodeStateStatus('completed')).toBe('done')
    expect(normalizeNodeStateStatus('failed')).toBe('error')
    expect(normalizeNodeStateStatus('waiting')).toBe('waiting')
    expect(normalizeWorkflowRunStatus('done')).toBe('completed')
    expect(normalizeWorkflowRunStatus('error')).toBe('failed')
  })

  it('keeps output, values, attempts, timestamps and cache facts', () => {
    const response = normalizeWorkflowRunResponse({
      run: {
        status: 'done' as any, output: { answer: 42 }, values: { 'a.out': 42 },
        node_states: { a: { status: 'completed' as any, output: 42, attempts: 2, cache_status: 'hit', cache_key: 'k1', startedAt: '2026-01-01T00:00:00Z', finishedAt: '2026-01-01T00:00:01Z' } as any },
        cache: { a: { status: 'hit', key: 'k1', hit: true, miss: false } },
        run_id: 'run-1', steps_remaining: 0,
      },
      thread_id: 'thread-1', run_id: 'run-1',
    })
    expect(response.run).toMatchObject({ status: 'completed', output: { answer: 42 }, values: { 'a.out': 42 } })
    expect(response.run.node_states.a).toMatchObject({ status: 'done', attempts: 2, output: 42, cache_status: 'hit', cache_key: 'k1', started_at: '2026-01-01T00:00:00Z' })
    expect(response.run.cache.a).toMatchObject({ status: 'hit', hit: true, miss: false, key: 'k1' })
  })
})

describe('workflow continuation adapter', () => {
  it('sends preferred continuation and legacy state for migration hosts', () => {
    expect(buildWorkflowRunPayload('demo', {
      runId: 'run-1', threadId: 'thread-1', modelId: 'model-1', permissions: { run_command: true }, maxSteps: 1,
      priorValues: { 'a.out': 1 },
      priorNodeStates: { a: { node_id: 'a', status: 'done' as any, attempts: 1 } },
      continuation: { token: 'next-token', state: { cursor: 1 }, runId: 'run-1' },
    })).toMatchObject({ continuation_token: 'next-token', continuation_state: { cursor: 1 }, prior_values: { 'a.out': 1 }, run_id: 'run-1', model_id: 'model-1', permissions: { run_command: true } })
  })

  it('falls back once when the host rejects continuation fields', async () => {
    const requestRpc = vi.fn()
      .mockRejectedValueOnce(new Error('unknown continuation parameter'))
      .mockResolvedValueOnce({ run: { status: 'paused', node_states: {}, values: {}, cache: {}, run_id: 'run-1', steps_remaining: 1 }, thread_id: 't', run_id: 'run-1' })
    const response = await createWorkflowApi(requestRpc).run('demo', { continuation: { token: 'next' }, runId: 'run-1' })
    expect(response.run.status).toBe('paused')
    expect(requestRpc).toHaveBeenCalledTimes(2)
    expect(requestRpc.mock.calls[1][1]).not.toHaveProperty('continuation_token')
  })
})

describe('workflow persistence and revision conflicts', () => {
  it('round-trips trigger declarations and policies through the canonical document', () => {
    const source = definition({
      triggers: [
        { id: 'manual', type: 'manual', enabled: true, name: '手动', inputs: { source: 'button' } },
        { id: 'once', type: 'once', enabled: true, at: '2026-09-14T09:00:00+08:00', max_runs: 1 },
        { id: 'interval', type: 'interval', enabled: true, every_seconds: 900, start_at: '2026-09-14T09:00:00+08:00' },
        { id: 'calendar', type: 'calendar', enabled: true, frequency: 'monthly', time: '08:30', timezone: 'Asia/Shanghai', day: 15 },
        { id: 'event', type: 'event', enabled: false, event_type: 'invoice.created' },
      ],
      policies: { concurrency: { limit: 2 }, retries: { max_attempts: 3 } },
    })
    const document = workflowDefinitionToDocument(source)
    expect(document.triggers).toEqual(source.triggers)
    expect(document.policies).toEqual(source.policies)
    const restored = workflowDocumentToDefinition(document)
    expect(restored.triggers).toEqual(source.triggers)
    expect(restored.policies).toEqual(source.policies)
  })

  it('round-trips structured transform and condition expression ASTs on links', () => {
    const transform = { version: 1, op: 'get', path: ['answer', 'value'] }
    const condition = { version: 1, op: 'compare', operator: 'gte', left: { op: 'get', path: ['score'] }, right: 0.8 }
    const source = definition({
      edges: [{ id: 'ast-edge', source: 'a', source_port: 'out', target: 'b', target_port: 'in', transform, condition }],
    })
    const document = workflowDefinitionToDocument(source)
    expect(document.graph.links[0]).toMatchObject({ transform, condition })
    const restored = workflowDocumentToDefinition(document)
    expect(restored.edges[0]).toMatchObject({ transform, condition })
  })

  it('uses explicit activation RPC operations and preserves activation payload fields', async () => {
    const activation = {
      id: 'activation-1', workflow_id: 'wf-1', workflow_name: 'demo', workflow_revision: 4,
      trigger_id: 'calendar', trigger_type: 'calendar', status: 'waiting', next_run_at: '2026-09-14T08:30:00+08:00',
      run_count: 2, max_runs: null, last_error: '', revision: 9,
    }
    const requestRpc = vi.fn(async (method: string) => {
      if (method === 'workflow.activate') return { activated: [activation], reused: [] }
      if (method === 'workflow.deactivate') return { cancelled: ['activation-1'] }
      if (method === 'workflow.activation.list') return { activations: [activation] }
      return {}
    })
    const api = createWorkflowApi(requestRpc)
    await expect(api.activate('demo', { workRoot: 'C:/work', triggerId: 'calendar', replace: true })).resolves.toMatchObject({ activated: [{ id: 'activation-1', workflow_revision: 4 }] })
    await expect(api.deactivate('demo', { workRoot: 'C:/work', triggerId: 'calendar' })).resolves.toEqual(['activation-1'])
    await expect(api.listActivations('demo', 'C:/work')).resolves.toMatchObject([{ status: 'waiting', revision: 9 }])
    expect(requestRpc.mock.calls[0]).toEqual(['workflow.activate', { name: 'demo', work_root: 'C:/work', trigger_id: 'calendar', replace: true }])
    expect(requestRpc.mock.calls[1]).toEqual(['workflow.deactivate', { name: 'demo', work_root: 'C:/work', trigger_id: 'calendar' }])
    expect(requestRpc.mock.calls[2]).toEqual(['workflow.activation.list', { name: 'demo', work_root: 'C:/work' }])
    expect(normalizeWorkflowActivations([activation])[0]).toMatchObject({ trigger_id: 'calendar', workflow_revision: 4 })
  })

  it('round-trips node parent_id through canvas and clears stale document views', () => {
    const source = definition({
      nodes: definition().nodes.map((item: WorkflowNode) => item.id === 'b' ? { ...item, parent_id: 'group-a' } : item),
    })
    const document = JSON.parse(serializeWorkflowJson(source)) as Record<string, any>
    expect(document.canvas.node_views.b.parent_id).toBe('group-a')
    expect(document.graph.nodes[1]).not.toHaveProperty('parent_id')

    const restored = normalizeImportedWorkflow(document) as WorkflowDef
    expect(restored.nodes.find((item: WorkflowNode) => item.id === 'b')?.parent_id).toBe('group-a')
    const legacyImported = normalizeImportedWorkflow({
      name: 'legacy',
      nodes: [{ id: 'legacy-node', kind: 'command', parentId: 'legacy-group' }],
    }) as WorkflowDef
    expect(legacyImported.nodes[0].parent_id).toBe('legacy-group')

    const cleared = {
      ...restored,
      nodes: restored.nodes.map((item: WorkflowNode) => item.id === 'b' ? { ...item, parent_id: undefined } : item),
    }
    const clearedDocument = JSON.parse(serializeWorkflowJson(cleared)) as Record<string, any>
    expect(clearedDocument.canvas.node_views.b).not.toHaveProperty('parent_id')
    expect((normalizeImportedWorkflow(clearedDocument) as WorkflowDef).nodes.find((item: WorkflowNode) => item.id === 'b')?.parent_id).toBeUndefined()
  })

  it('loads and saves the canonical V2 document without sending a legacy map', async () => {
    const document = {
      format: 'lamtools.workflow', version: 2,
      resource: { id: 'wf-1', name: 'demo', description: '', work_root: 'C:/work', revision: 4, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
      graph: {
        nodes: [
          { id: 'a', type: { id: 'command', version: 1 }, title: 'a', ports: [{ id: 'port-a-out', name: 'out', direction: 'out', data_type: 'string', description: '', required: false, lazy: false }], params: { command: 'echo ok' }, execution: { enabled: true, schema_only: false, cache: 'auto', on_error: { strategy: 'abort' }, permissions: [] } },
          { id: 'b', type: { id: 'command', version: 1 }, title: 'b', ports: [{ id: 'port-b-in', name: 'in', direction: 'in', data_type: 'string', description: '', required: true, lazy: false }], params: {}, execution: { enabled: true, schema_only: false, cache: 'auto', on_error: { strategy: 'abort' }, permissions: [] } },
        ],
        links: [{ id: 'link-stable', source: { node_id: 'a', port_id: 'port-a-out' }, target: { node_id: 'b', port_id: 'port-b-in' } }],
      },
      interface: { inputs: [], outputs: [{ id: 'result', name: 'out', data_type: 'string', description: '', source: { node_id: 'a', port_id: 'port-a-out' } }] },
      exposure: { enabled: false, tool_name: '' },
      canvas: { viewport: { x: 12, y: 18, zoom: 0.8 }, node_views: { a: { position: { x: 20, y: 40 } }, b: { position: { x: 300, y: 40 } } }, groups: [], reroutes: [], annotations: [] },
    }
    const requestRpc = vi.fn()
      .mockResolvedValueOnce({ document })
      .mockResolvedValueOnce({ document: { ...document, resource: { ...document.resource, revision: 5 } } })
    const api = createWorkflowApi(requestRpc)
    const loaded = await api.getDocumentById('wf-1', 'C:/work')
    expect(loaded.revision).toBe(4)
    expect(loaded.map).toBe('')
    expect(loaded.nodes[0].ports[0].id).toBe('port-a-out')
    expect(loaded.edges[0]).toMatchObject({ id: 'link-stable', source_port_id: 'port-a-out', target_port_id: 'port-b-in' })
    expect(loaded.document?.canvas.viewport).toEqual({ x: 12, y: 18, zoom: 0.8 })
    await api.saveDocument(loaded, 'C:/work')
    expect(requestRpc.mock.calls.map(([method]) => method)).toEqual(['workflow.document.get', 'workflow.document.save'])
    expect(requestRpc.mock.calls[1][1]).toMatchObject({
      expected_revision: 4,
      document: {
        format: 'lamtools.workflow', version: 2,
        graph: { links: [{ id: 'link-stable', source: { port_id: 'port-a-out' }, target: { port_id: 'port-b-in' } }] },
      },
    })
    expect(requestRpc.mock.calls[1][1].document).not.toHaveProperty('map')
  })

  it('falls back to legacy persistence only when the document operation is unregistered', async () => {
    const requestRpc = vi.fn()
      .mockRejectedValueOnce(new Error('Operation is not registered: workflow.document.get'))
      .mockResolvedValueOnce({ workflow: definition() })
    await expect(createWorkflowApi(requestRpc).getDocument('demo')).resolves.toMatchObject({ id: 'wf-1' })
    expect(requestRpc.mock.calls.map(([method]) => method)).toEqual(['workflow.document.get', 'workflow.get'])

    const validationRpc = vi.fn().mockRejectedValue(new Error('workflow graph contains a cycle'))
    await expect(createWorkflowApi(validationRpc).getDocument('demo')).rejects.toThrow('cycle')
    expect(validationRpc).toHaveBeenCalledTimes(1)
  })

  it('does not grow canvas collections across consecutive V2 round-trips', async () => {
    const canonical = {
      format: 'lamtools.workflow', version: 2,
      resource: { id: 'wf-canvas', name: 'canvas', description: '', work_root: '', revision: 1, created_at: '', updated_at: '' },
      graph: { nodes: [], links: [] }, interface: { inputs: [], outputs: [] }, exposure: { enabled: false, tool_name: '' },
      canvas: {
        viewport: { x: 0, y: 0, zoom: 1 }, node_views: {},
        groups: [{ title: 'Comfy group', bounding: [1, 2, 300, 180], vendor_flag: true }],
        reroutes: [{ pos: [20, 30], linkIds: [1] }],
        annotations: [{ kind: 'note', title: 'Note', position: { x: 8, y: 9 }, width: 160, height: 80 }],
      },
    }
    const requestRpc = vi.fn(async (method: string, params: Record<string, unknown> = {}) => (
      method === 'workflow.document.get' ? { document: canonical } : { document: params.document }
    ))
    const api = createWorkflowApi(requestRpc)
    let current = await api.getDocument('canvas')
    current = await api.saveDocument(current)
    current = await api.saveDocument(current)
    const savedDocuments = requestRpc.mock.calls
      .filter(([method]) => method === 'workflow.document.save')
      .map(([, params]) => (params?.document ?? {}) as Record<string, any>)
    expect(savedDocuments.map((item) => [item.canvas.groups.length, item.canvas.reroutes.length, item.canvas.annotations.length])).toEqual([[1, 1, 1], [1, 1, 1]])
    expect(savedDocuments[1].canvas.groups[0]).toMatchObject({ vendor_flag: true, data: { bounding: [1, 2, 300, 180], vendor_flag: true } })
  })

  it('sends expected_revision for save and update', async () => {
    const requestRpc = vi.fn()
      .mockResolvedValueOnce({ workflow: definition({ revision: 2 }) })
      .mockResolvedValueOnce({ workflow: definition({ revision: 3 }) })
    const api = createWorkflowApi(requestRpc)
    await api.save(definition({ revision: 2 }), 'C:/work')
    await api.update('demo', { description: 'new' }, 'C:/work', 3)
    expect(requestRpc.mock.calls[0][1]).toMatchObject({ expected_revision: 2, workflow: { expected_revision: 2 } })
    expect(requestRpc.mock.calls[1][1]).toMatchObject({ expected_revision: 3 })
  })

  it('detects structured 409/revision conflict errors', () => {
    expect(isWorkflowRevisionConflict({ code: 409, data: { message: 'stale writer' } })).toBe(true)
    expect(isWorkflowRevisionConflict(new Error('workflow revision conflict'))).toBe(true)
    expect(isWorkflowRevisionConflict(new Error('network unavailable'))).toBe(false)
  })
})

describe('workflow command/document and ports', () => {
  it('supports undo/redo plus dirty/save-error/conflict state', async () => {
    const current = definition()
    const document = createWorkflowDocument(current)
    document.update({ ...current, name: 'changed' }, { label: '重命名' })
    expect(document.snapshot()).toMatchObject({ dirty: true, canUndo: true })
    expect(document.undo()?.name).toBe('demo')
    expect(document.redo()?.name).toBe('changed')
    document.markSaveError(new Error('offline'))
    expect(document.snapshot().saveError).toMatchObject({ kind: 'save-error', message: 'offline' })
    document.markSaved(document.snapshot().definition, { value: 2 })
    expect(document.snapshot()).toMatchObject({ dirty: false, saveError: null, revision: { value: 2 } })
    document.update({ ...current, description: 'local' })
    document.markConflict({ ...current, description: 'remote', revision: 3 })
    expect(document.snapshot().definition.description).toBe('local')
    expect(document.snapshot().conflict?.remote.description).toBe('remote')
    expect(document.keepLocalAfterConflict()).toBe(true)
    expect(document.snapshot()).toMatchObject({ dirty: true, conflict: null, revision: { value: 3 } })
    // The rebased revision must also be carried by the definition passed to
    // the next save; otherwise the adapter derives a stale CAS revision.
    expect(document.snapshot().definition.revision).toBe(3)

    const requestRpc = vi.fn().mockResolvedValue({ workflow: definition({ revision: 4, description: 'local' }) })
    await createWorkflowApi(requestRpc).save(document.snapshot().definition)
    expect(requestRpc.mock.calls[0][1]).toMatchObject({
      expected_revision: 3,
      workflow: { expected_revision: 3, description: 'local', revision: 3 },
    })
  })

  it('updates connected edges on rename and rejects connected deletion', () => {
    const current = definition()
    const previous = current.nodes[0]
    const renamed = { ...previous, ports: previous.ports.map((port: any) => port.name === 'out' ? { ...port, name: 'result' } : port) }
    const renameResult = reconcileWorkflowNodePorts(current, previous, renamed)
    expect(renameResult.ok).toBe(true)
    if (renameResult.ok) expect(renameResult.definition.edges[0].source_port).toBe('result')
    const removed = { ...previous, ports: previous.ports.filter((port: any) => port.name !== 'out') }
    const deleteResult = reconcileWorkflowNodePorts(current, previous, removed)
    expect(deleteResult.ok).toBe(false)
    if (!deleteResult.ok) expect(deleteResult.danglingEdges.map((edge: any) => edge.id)).toEqual(['e1'])
  })

  it('rejects port reordering instead of retargeting connected edges', () => {
    const current = definition({
      nodes: [
        node('a', [
          { name: 'first', type: 'string', direction: 'out' },
          { name: 'second', type: 'string', direction: 'out' },
        ]),
        node('b', [{ name: 'in', type: 'string', direction: 'in' }]),
      ],
      edges: [{ id: 'e1', source: 'a', source_port: 'first', target: 'b', target_port: 'in' }],
    })
    const previous = current.nodes[0]
    const reordered = { ...previous, ports: [previous.ports[1], previous.ports[0]] }
    const result = reconcileWorkflowNodePorts(current, previous, reordered)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.reason).toContain('顺序不能更改')
  })
})
