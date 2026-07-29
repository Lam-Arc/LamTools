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
  } = {},
): Promise<{ run: WorkflowRunResult; thread_id: string; run_id: string }> {
  const params: Record<string, unknown> = { name }
  if (options.workRoot) params.work_root = options.workRoot
  if (options.inputs) params.inputs = options.inputs
  if (options.maxSteps !== undefined) params.max_steps = options.maxSteps
  if (options.priorValues) params.prior_values = options.priorValues
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
