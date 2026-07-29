/** Workflow JSON-RPC client (mirrors durable/api.ts). */

import { appServerUrl, CoreAppServerClient } from '../appServer'
import type { WorkflowDef, WorkflowRunResult } from './types'

async function appServerOperation<T>(
  method: string,
  params: Record<string, unknown> = {},
): Promise<T> {
  const client = new CoreAppServerClient({
    url: appServerUrl('', { path: '/api/core/app-server' }),
    clientInfo: { name: 'core_ui', title: 'Core', version: '0.1.0' },
  })
  try {
    await client.connect()
    return (await client.request(method, params)) as T
  } finally {
    client.close()
  }
}

export function listWorkflows(workRoot?: string): Promise<WorkflowDef[]> {
  const params: Record<string, unknown> = {}
  if (workRoot) params.work_root = workRoot
  return appServerOperation<{ workflows?: WorkflowDef[] }>('workflow.list', params).then(
    (r) => r.workflows ?? [],
  )
}

export function listGroupedWorkflows(workRoots: string[]): Promise<Record<string, WorkflowDef[]>> {
  const params: Record<string, unknown> = { work_roots: workRoots }
  return appServerOperation<{ groups?: Record<string, WorkflowDef[]> }>(
    'workflow.list_grouped',
    params,
  ).then((r) => r.groups ?? {})
}

export function getWorkflow(name: string, workRoot?: string): Promise<WorkflowDef> {
  const params: Record<string, unknown> = { name }
  if (workRoot) params.work_root = workRoot
  return appServerOperation<{ workflow?: WorkflowDef }>('workflow.get', params).then((r) => {
    if (!r.workflow) throw new Error('workflow.get response is missing workflow')
    return r.workflow
  })
}

export function createWorkflow(definition: Record<string, unknown>): Promise<WorkflowDef> {
  return appServerOperation<{ workflow?: WorkflowDef }>('workflow.create', definition).then((r) => {
    if (!r.workflow) throw new Error('workflow.create response is missing workflow')
    return r.workflow
  })
}

export function updateWorkflow(
  name: string,
  fields: Record<string, unknown>,
  workRoot?: string,
): Promise<WorkflowDef> {
  const params: Record<string, unknown> = { name, ...fields }
  if (workRoot) params.work_root = workRoot
  return appServerOperation<{ workflow?: WorkflowDef }>('workflow.update', params).then((r) => {
    if (!r.workflow) throw new Error('workflow.update response is missing workflow')
    return r.workflow
  })
}

export function deleteWorkflow(name: string, workRoot?: string): Promise<boolean> {
  const params: Record<string, unknown> = { name }
  if (workRoot) params.work_root = workRoot
  return appServerOperation<{ deleted?: boolean }>('workflow.delete', params).then(
    (r) => !!r.deleted,
  )
}

export function runWorkflow(
  name: string,
  options: {
    workRoot?: string
    inputs?: Record<string, unknown>
    maxSteps?: number
    priorValues?: Record<string, unknown>
    startNode?: string
    singleNode?: string
  } = {},
): Promise<{ run: WorkflowRunResult; thread_id: string; run_id: string }> {
  const params: Record<string, unknown> = { name }
  if (options.workRoot) params.work_root = options.workRoot
  if (options.inputs) params.inputs = options.inputs
  if (options.maxSteps !== undefined) params.max_steps = options.maxSteps
  if (options.priorValues) params.prior_values = options.priorValues
  if (options.startNode) params.start_node = options.startNode
  if (options.singleNode) params.single_node = options.singleNode
  return appServerOperation<{ run?: WorkflowRunResult; thread_id?: string; run_id?: string }>(
    'workflow.run',
    params,
  ).then((r) => {
    if (!r.run) throw new Error('workflow.run response is missing run')
    return { run: r.run, thread_id: r.thread_id ?? '', run_id: r.run_id ?? '' }
  })
}

export function setWorkflowExposed(
  name: string,
  exposed: boolean,
  workRoot?: string,
): Promise<WorkflowDef> {
  const params: Record<string, unknown> = { name }
  if (workRoot) params.work_root = workRoot
  return appServerOperation<{ workflow?: WorkflowDef }>(
    exposed ? 'workflow.expose' : 'workflow.unexpose',
    params,
  ).then((r) => {
    if (!r.workflow) throw new Error('workflow expose response is missing workflow')
    return r.workflow
  })
}

export async function listToolNames(): Promise<Array<{ name: string; description: string }>> {
  const r = await appServerOperation<{ tools?: Array<{ name: string; description: string }> }>(
    'workflow.tools.list',
    {},
  )
  return r.tools ?? []
}

export interface WorkflowEditMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface WorkflowEditResult {
  reply: string
  workflow: WorkflowDef
  applied: boolean
}

export function editWorkflow(
  name: string,
  options: {
    message: string
    history?: WorkflowEditMessage[]
    workRoot?: string
    modelId?: string
    reasoningEffort?: string
    temperature?: number
  },
): Promise<WorkflowEditResult> {
  const params: Record<string, unknown> = { name, message: options.message }
  if (options.workRoot) params.work_root = options.workRoot
  if (options.history?.length) params.history = options.history
  if (options.modelId) params.model_id = options.modelId
  if (options.reasoningEffort) params.reasoning_effort = options.reasoningEffort
  if (options.temperature !== undefined) params.temperature = options.temperature
  return appServerOperation<{ reply?: string; workflow?: WorkflowDef; applied?: boolean }>(
    'workflow.edit',
    params,
  ).then((r) => ({
    reply: r.reply ?? '',
    workflow: r.workflow ?? { name, description: '', nodes: [], edges: [], input_params: [], output_port: '', exposed: false, tool_name: '', work_root: options.workRoot ?? '', created_at: '', updated_at: '' },
    applied: !!r.applied,
  }))
}
