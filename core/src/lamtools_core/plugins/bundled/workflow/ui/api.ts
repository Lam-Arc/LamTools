import type { PluginRpc } from '../../../../../../ui/src/plugins/types'
import type { WorkflowDef, WorkflowRunResult } from './types'

export interface WorkflowApi {
  list(workRoot?: string): Promise<WorkflowDef[]>
  listGrouped(workRoots: string[]): Promise<Record<string, WorkflowDef[]>>
  get(name: string, workRoot?: string): Promise<WorkflowDef>
  getById(workflowId: string, workRoot?: string): Promise<WorkflowDef>
  create(definition: Record<string, unknown>): Promise<WorkflowDef>
  update(name: string, fields: Record<string, unknown>, workRoot?: string): Promise<WorkflowDef>
  save(definition: WorkflowDef, workRoot?: string): Promise<WorkflowDef>
  rename(name: string, newName: string, workRoot?: string): Promise<WorkflowDef>
  delete(name: string, workRoot?: string): Promise<boolean>
  run(name: string, options?: WorkflowRunOptions): Promise<WorkflowRunResponse>
  cancel(threadId: string, runId?: string): Promise<WorkflowCancelResponse>
  setExposed(name: string, exposed: boolean, workRoot?: string): Promise<WorkflowDef>
  listTools(): Promise<Array<{ name: string; description: string }>>
}

export interface WorkflowRunOptions {
  workRoot?: string
  inputs?: Record<string, unknown>
  maxSteps?: number
  priorValues?: Record<string, unknown>
  startNode?: string
  singleNode?: string
  runId?: string
  threadId?: string
}

export interface WorkflowRunResponse {
  run: WorkflowRunResult
  thread_id: string
  run_id: string
}

export interface WorkflowCancelResponse {
  cancelled: boolean
  thread_id: string
  run_id: string
}

export function createWorkflowApi(requestRpc: PluginRpc): WorkflowApi {
  async function operation<T extends Record<string, unknown>>(
    method: string,
    params: Record<string, unknown> = {},
  ): Promise<T> {
    return await requestRpc(method, params) as T
  }

  return {
    list(workRoot) {
      return operation<{ workflows?: WorkflowDef[] }>('workflow.list', workRoot ? { work_root: workRoot } : {})
        .then((result) => result.workflows ?? [])
    },
    listGrouped(workRoots) {
      return operation<{ groups?: Record<string, WorkflowDef[]> }>('workflow.list_grouped', { work_roots: workRoots })
        .then((result) => result.groups ?? {})
    },
    get(name, workRoot) {
      return operation<{ workflow?: WorkflowDef }>('workflow.get', {
        name,
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then(requireWorkflow('workflow.get'))
    },
    getById(workflowId, workRoot) {
      return operation<{ workflow?: WorkflowDef }>('workflow.get', {
        workflow_id: workflowId,
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then(requireWorkflow('workflow.get'))
    },
    create(definition) {
      return operation<{ workflow?: WorkflowDef }>('workflow.create', definition)
        .then(requireWorkflow('workflow.create'))
    },
    update(name, fields, workRoot) {
      return operation<{ workflow?: WorkflowDef }>('workflow.update', {
        name,
        ...fields,
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then(requireWorkflow('workflow.update'))
    },
    save(definition, workRoot) {
      return operation<{ workflow?: WorkflowDef }>('workflow.save', {
        workflow: definition,
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then(requireWorkflow('workflow.save'))
    },
    rename(name, newName, workRoot) {
      return operation<{ workflow?: WorkflowDef }>('workflow.rename', {
        name,
        new_name: newName,
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then(requireWorkflow('workflow.rename'))
    },
    delete(name, workRoot) {
      return operation<{ deleted?: boolean }>('workflow.delete', {
        name,
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then((result) => result.deleted === true)
    },
    run(name, options = {}) {
      return operation<Partial<WorkflowRunResponse> & { run?: WorkflowRunResult }>('workflow.run', {
        name,
        ...(options.workRoot ? { work_root: options.workRoot } : {}),
        ...(options.inputs ? { inputs: options.inputs } : {}),
        ...(options.maxSteps !== undefined ? { max_steps: options.maxSteps } : {}),
        ...(options.priorValues ? { prior_values: options.priorValues } : {}),
        ...(options.startNode ? { start_node: options.startNode } : {}),
        ...(options.singleNode ? { single_node: options.singleNode } : {}),
        ...(options.runId ? { run_id: options.runId } : {}),
        ...(options.threadId ? { thread_id: options.threadId } : {}),
      }).then((result) => {
        if (!result.run) throw new Error('workflow.run response is missing run')
        return {
          run: result.run,
          thread_id: result.thread_id ?? '',
          run_id: result.run_id ?? result.run.run_id ?? '',
        }
      })
    },
    cancel(threadId, runId) {
      return operation<Partial<WorkflowCancelResponse>>('workflow.cancel', {
        thread_id: threadId,
        ...(runId ? { run_id: runId } : {}),
      }).then((result) => ({
        cancelled: result.cancelled === true,
        thread_id: result.thread_id ?? threadId,
        run_id: result.run_id ?? runId ?? '',
      }))
    },
    setExposed(name, exposed, workRoot) {
      return operation<{ workflow?: WorkflowDef }>(exposed ? 'workflow.expose' : 'workflow.unexpose', {
        name,
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then(requireWorkflow(exposed ? 'workflow.expose' : 'workflow.unexpose'))
    },
    listTools() {
      return operation<{ tools?: Array<{ name: string; description: string }> }>('workflow.tools.list')
        .then((result) => result.tools ?? [])
    },
  }
}

function requireWorkflow(method: string) {
  return (result: { workflow?: WorkflowDef }): WorkflowDef => {
    if (!result.workflow) throw new Error(`${method} response is missing workflow`)
    return result.workflow
  }
}
