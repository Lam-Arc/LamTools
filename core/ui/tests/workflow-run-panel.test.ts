import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { SchemaNodeEditor, WorkflowNodeRuntimeDock, normalizeWorkflowNodeState } from '@lamtools/bundled-workflow-ui'

describe('workflow node runtime dock', () => {
  it('renders live node details beside the node and filters hidden reasoning fields', () => {
    const wrapper = mount(WorkflowNodeRuntimeDock, {
      props: {
        nodeId: 'model-1',
        title: '模型节点',
        kind: 'model',
        state: 'running',
        timeline: [{
          id: 'event-1',
          node_id: 'model-1',
          title: '模型节点',
          status: 'running',
          occurred_at: '2026-09-14T10:00:01Z',
          input: { prompt: 'hello' },
          output: { answer: 'ok' },
          attempts: 2,
          duration_ms: 1200,
          tool_calls: [{ name: 'search', status: 'completed' }],
          logs: [{ reasoning: 'hidden chain_of_thought should not render', message: 'completed' }],
          audit: { kind: 'node.completed', tool_calls: [{ name: 'search', status: 'completed' }] },
          error: '公开错误',
        }],
      },
    })

    expect(wrapper.text()).toContain('运行中')
    expect(wrapper.text()).toContain('实时')
    expect(wrapper.text()).toContain('1.2 s')
    expect(wrapper.text()).toContain('工具调用')
    expect(wrapper.text()).toContain('日志')
    expect(wrapper.text()).not.toContain('chain_of_thought')
    expect(wrapper.text()).not.toContain('reasoning: hidden')
    wrapper.unmount()
  })

  it('keeps pending approval actions on the approval node', async () => {
    const complete = vi.fn()
    const task = {
      task_id: 'task-1', id: 'task-1', status: 'pending', run_id: 'run-1', run: 'run-1',
      thread_id: 'thread-1', thread: 'thread-1', workflow_id: 'wf-1', workflow_name: 'demo', workflow: 'demo',
      workflow_revision: 1, revision: 1, node_id: 'approval-1', node: 'approval-1', kind: 'approval',
      title: '发布审批', form: { reason: '生产环境' }, event_type: 'approval',
    } as any
    const wrapper = mount(WorkflowNodeRuntimeDock, {
      props: {
        nodeId: 'approval-1', title: '发布审批', kind: 'approval', state: 'waiting',
        humanTasks: [task], selectedHumanTask: task, onCompleteHumanTask: complete,
      },
    })

    expect(wrapper.text()).toContain('等待操作')
    expect(wrapper.text()).toContain('批准')
    expect(wrapper.text()).toContain('拒绝')
    await wrapper.get('.wf-human-task-action.primary').trigger('click')
    expect(complete).toHaveBeenCalledWith(task, 'approve', {})
    wrapper.unmount()
  })

  it('collapses completed output into a status marker', async () => {
    const wrapper = mount(WorkflowNodeRuntimeDock, {
      props: {
        nodeId: 'output-1', title: '输出', kind: 'output', state: 'done',
        detail: { node_id: 'output-1', status: 'done', output: { answer: 'ready' }, attempts: 1 },
      },
    })
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).not.toContain('ready')
    await wrapper.get('.wf-node-runtime-summary').trigger('click')
    expect(wrapper.text()).toContain('ready')
    wrapper.unmount()
  })
})

describe('workflow schema editor affordances', () => {
  it('uses localized parameter labels and only offers port sync when ports are missing', () => {
    const schema = {
      name: 'model', type_id: 'model', display_name: 'Model', description: 'Generate a result',
      input: { required: { prompt: { type: 'string', description: 'Text to generate from' } } },
      output: { output: { type: 'string' } },
    } as any
    const complete = mount(SchemaNodeEditor, {
      props: {
        schema,
        modelValue: {},
        ports: [
          { name: 'prompt', type: 'string', direction: 'in' },
          { name: 'output', type: 'string', direction: 'out' },
        ],
      },
    })
    expect(complete.text()).toContain('节点参数')
    expect(complete.text()).toContain('提示词')
    expect(complete.text()).not.toContain('Schema 配置')
    expect(complete.find('.wf-schema-sync').exists()).toBe(false)
    complete.unmount()

    const missing = mount(SchemaNodeEditor, { props: { schema, modelValue: {}, ports: [] } })
    expect(missing.find('.wf-schema-sync').exists()).toBe(true)
    expect(missing.text()).toContain('补齐缺少的端口')
    missing.unmount()
  })

  it('does not render an empty parameter shell for structural nodes', () => {
    const wrapper = mount(SchemaNodeEditor, {
      props: {
        schema: { name: 'output', type_id: 'output', display_name: 'Output', description: 'Workflow output' } as any,
        modelValue: {},
        ports: [],
      },
    })
    expect(wrapper.find('.wf-schema-editor').exists()).toBe(false)
    wrapper.unmount()
  })

  it('retains input/output and audit fields at the normalization boundary', () => {
    expect(normalizeWorkflowNodeState({
      node_id: 'node-1', status: 'completed', input: { prompt: 'hi' }, output: 'ok', attempts: 2,
      duration_ms: 50, tool_calls: [{ name: 'search' }], logs: ['done'], audit: { kind: 'completed', tool_calls: [{ name: 'search' }] },
    })).toMatchObject({
      node_id: 'node-1', status: 'done', input: { prompt: 'hi' }, output: 'ok', attempts: 2,
      duration_ms: 50, tool_calls: [{ name: 'search' }], logs: ['done'], audit: { kind: 'completed', tool_calls: [{ name: 'search' }] },
    })
  })
})
