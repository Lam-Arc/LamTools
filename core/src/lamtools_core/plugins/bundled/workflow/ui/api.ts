import type { PluginRpc } from '../../../../../../ui/src/plugins/types'
import {
  normalizeNodeStateStatus,
  normalizeWorkflowRunStatus,
  type WorkflowDef,
  type WorkflowCacheFact,
  type WorkflowNodeSchema,
  type WorkflowQueueItem,
  type WorkflowQueueStatus,
  type WorkflowNodeState,
  type WorkflowRunResult,
  type WorkflowDocumentV2,
  type WorkflowActivation,
  type WorkflowHumanTask,
} from './types'
import {
  isWorkflowDocumentV2,
  workflowDefinitionToDocument,
  workflowDocumentToDefinition,
} from './document'

export interface WorkflowApi {
  list(workRoot?: string): Promise<WorkflowDef[]>
  listGrouped(workRoots: string[]): Promise<Record<string, WorkflowDef[]>>
  get(name: string, workRoot?: string): Promise<WorkflowDef>
  getById(workflowId: string, workRoot?: string): Promise<WorkflowDef>
  getDocument(name: string, workRoot?: string): Promise<WorkflowDef>
  getDocumentById(workflowId: string, workRoot?: string): Promise<WorkflowDef>
  create(definition: Record<string, unknown> | WorkflowDef): Promise<WorkflowDef>
  update(name: string, fields: Record<string, unknown>, workRoot?: string, expectedRevision?: number | string): Promise<WorkflowDef>
  save(definition: WorkflowDef, workRoot?: string, expectedRevision?: number | string): Promise<WorkflowDef>
  saveDocument(definition: WorkflowDef | WorkflowDocumentV2, workRoot?: string, expectedRevision?: number | string): Promise<WorkflowDef>
  rename(name: string, newName: string, workRoot?: string): Promise<WorkflowDef>
  delete(name: string, workRoot?: string): Promise<boolean>
  run(name: string, options?: WorkflowRunOptions): Promise<WorkflowRunResponse>
  cancel(threadId: string, runId?: string): Promise<WorkflowCancelResponse>
  activate(name: string, options?: WorkflowActivationOptions): Promise<{ activated: WorkflowActivation[]; reused: WorkflowActivation[] }>
  deactivate(name: string, options?: WorkflowActivationOptions): Promise<string[]>
  listActivations(name: string, workRoot?: string): Promise<WorkflowActivation[]>
  objectInfo(nodeType?: string): Promise<Record<string, WorkflowNodeSchema>>
  enqueue(name: string, options?: WorkflowQueueOptions): Promise<WorkflowQueueItem>
  listQueue(options?: WorkflowQueueQuery): Promise<WorkflowQueueItem[]>
  historyQueue(options?: WorkflowQueueQuery): Promise<WorkflowQueueItem[]>
  getQueue(queueId?: string, runId?: string): Promise<WorkflowQueueItem>
  clearQueue(options?: WorkflowQueueClearOptions): Promise<number>
  cancelQueue(queueId?: string, runId?: string): Promise<WorkflowQueueItem>
  setExposed(name: string, exposed: boolean, workRoot?: string): Promise<WorkflowDef>
  listTools(): Promise<Array<{ name: string; description: string }>>
  importComfyUi(workflow: Record<string, unknown>, name: string, workRoot?: string, expectedRevision?: number | string): Promise<WorkflowDef>
  exportComfyUi(name: string, version: '0.4' | '1', workRoot?: string): Promise<Record<string, unknown>>
  listHumanTasks(options?: WorkflowHumanTaskQuery): Promise<WorkflowHumanTask[]>
  getHumanTask(taskId: string, options?: WorkflowHumanTaskScope): Promise<WorkflowHumanTask>
  completeHumanTask(taskId: string, decision?: 'approve' | 'reject' | string, payload?: Record<string, unknown>, options?: WorkflowHumanTaskScope): Promise<WorkflowHumanTaskCompletion>
}

export interface WorkflowRunOptions {
  workRoot?: string
  modelId?: string
  permissions?: Record<string, unknown>
  inputs?: Record<string, unknown>
  maxSteps?: number
  priorValues?: Record<string, unknown>
  /** Legacy resume state accepted by the current runner. */
  priorNodeStates?: Record<string, WorkflowNodeState>
  /** Preferred continuation contract; kept opaque so the backend can evolve. */
  continuation?: WorkflowContinuationState
  startNode?: string
  singleNode?: string
  runId?: string
  threadId?: string
}

export interface WorkflowContinuationState {
  token?: string
  state?: unknown
  runId?: string
}

export interface WorkflowRunResponse {
  run: WorkflowRunResult
  thread_id: string
  run_id: string
  continuation?: WorkflowContinuationState
}

export interface WorkflowCancelResponse {
  cancelled: boolean
  thread_id: string
  run_id: string
}

export interface WorkflowActivationOptions {
  workRoot?: string
  triggerId?: string
  replace?: boolean
}

export interface WorkflowQueueOptions {
  workRoot?: string
  modelId?: string
  permissions?: Record<string, unknown>
  inputs?: Record<string, unknown>
  maxSteps?: number
  startNode?: string
  singleNode?: string
  priorValues?: Record<string, unknown>
  priorNodeStates?: Record<string, WorkflowNodeState>
  threadId?: string
  runId?: string
  metadata?: Record<string, unknown>
}

export interface WorkflowQueueQuery {
  workRoot?: string
  workflowId?: string
  name?: string
  status?: WorkflowQueueStatus | WorkflowQueueStatus[]
  includeHistory?: boolean
  includeActive?: boolean
  limit?: number
}

export interface WorkflowQueueClearOptions {
  confirm?: boolean
  all?: boolean
  workRoot?: string
  workflowId?: string
  name?: string
}

export interface WorkflowHumanTaskScope {
  workRoot?: string
  all?: boolean
}

export interface WorkflowHumanTaskQuery extends WorkflowHumanTaskScope {
  status?: 'pending' | 'completed' | 'all' | string
  workflowId?: string
  workflowName?: string
  threadId?: string
  limit?: number
  includeAudit?: boolean
}

export interface WorkflowHumanTaskCompletion {
  task: WorkflowHumanTask
  run?: Record<string, unknown> | null
  idempotent?: boolean
  timed_out?: boolean
}

export function createWorkflowApi(requestRpc: PluginRpc): WorkflowApi {
  async function operation<T extends Record<string, unknown>>(
    method: string,
    params: Record<string, unknown> = {},
  ): Promise<T> {
    const result = await requestRpc(method, params) as T
    if (result && typeof result === 'object' && 'error' in result && result.error) {
      const payload = result as T & { error?: unknown; code?: unknown; status?: unknown }
      const errorValue = payload.error
      const message = errorValue && typeof errorValue === 'object' && 'message' in errorValue
        ? String((errorValue as { message?: unknown }).message || errorValue)
        : String(errorValue)
      const error = new Error(message)
      Object.assign(error, {
        code: payload.code ?? payload.status,
        data: payload,
      })
      throw error
    }
    return result
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
    getDocument(name, workRoot) {
      const params = {
        name,
        ...(workRoot ? { work_root: workRoot } : {}),
      }
      return operation<WorkflowDocumentEnvelope>('workflow.document.get', params)
        .then(requireWorkflowDocument('workflow.document.get'))
        .catch((error) => {
          if (!isWorkflowOperationUnsupported(error, 'workflow.document.get')) throw error
          return operation<{ workflow?: WorkflowDef }>('workflow.get', params)
            .then(requireWorkflow('workflow.get'))
        })
    },
    getDocumentById(workflowId, workRoot) {
      const params = {
        workflow_id: workflowId,
        ...(workRoot ? { work_root: workRoot } : {}),
      }
      return operation<WorkflowDocumentEnvelope>('workflow.document.get', params)
        .then(requireWorkflowDocument('workflow.document.get'))
        .catch((error) => {
          if (!isWorkflowOperationUnsupported(error, 'workflow.document.get')) throw error
          return operation<{ workflow?: WorkflowDef }>('workflow.get', params)
            .then(requireWorkflow('workflow.get'))
        })
    },
    create(definition) {
      return operation<{ workflow?: WorkflowDef }>('workflow.create', definition as Record<string, unknown>)
        .then(requireWorkflow('workflow.create'))
    },
    update(name, fields, workRoot, expectedRevision) {
      return operation<{ workflow?: WorkflowDef }>('workflow.update', {
        name,
        ...fields,
        ...expectedRevisionField(expectedRevision ?? fields.revision),
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then(requireWorkflow('workflow.update'))
    },
    save(definition, workRoot, expectedRevision = definition.revision) {
      const workflow = {
        ...definition,
        ...expectedRevisionField(expectedRevision),
      }
      return operation<{ workflow?: WorkflowDef }>('workflow.save', {
        workflow,
        // Keep the top-level alias for hosts that inspect the envelope before
        // applying the nested workflow payload. The current backend consumes
        // the nested value after extracting `workflow`.
        ...expectedRevisionField(expectedRevision),
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then(requireWorkflow('workflow.save'))
    },
    saveDocument(definition, workRoot, expectedRevision = isWorkflowDocumentV2(definition) ? definition.resource.revision : definition.revision) {
      const document = isWorkflowDocumentV2(definition) ? definition : workflowDefinitionToDocument(definition)
      const params = {
        document,
        ...expectedRevisionField(expectedRevision),
        ...(workRoot ? { work_root: workRoot } : {}),
      }
      return operation<WorkflowDocumentEnvelope>('workflow.document.save', params)
        .then(requireWorkflowDocument('workflow.document.save'))
        .catch((error) => {
          if (!isWorkflowOperationUnsupported(error, 'workflow.document.save')) throw error
          const workflow = {
            ...definition,
            ...expectedRevisionField(expectedRevision),
          }
          if (isWorkflowDocumentV2(definition)) throw error
          return operation<{ workflow?: WorkflowDef }>('workflow.save', {
            workflow,
            ...expectedRevisionField(expectedRevision),
            ...(workRoot ? { work_root: workRoot } : {}),
          }).then(requireWorkflow('workflow.save'))
        })
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
      const modernPayload = buildWorkflowRunPayload(name, options, true)
      return operation<RawWorkflowRunResponse>('workflow.run', modernPayload)
        .catch((error) => {
          // During the backend migration an older host may reject the new
          // continuation fields. Retry once with the established
          // prior_values/prior_node_states contract; ordinary run errors and
          // invalid continuation tokens must remain visible to the caller.
          if (!options.continuation || !isContinuationContractUnsupported(error)) throw error
          return operation<RawWorkflowRunResponse>('workflow.run', buildWorkflowRunPayload(name, options, false))
        })
        .then(normalizeWorkflowRunResponse)
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
    activate(name, options = {}) {
      return operation<Record<string, unknown>>('workflow.activate', {
        name,
        ...(options.workRoot ? { work_root: options.workRoot } : {}),
        ...(options.triggerId ? { trigger_id: options.triggerId } : {}),
        ...(options.replace ? { replace: true } : {}),
      }).then((result) => ({
        activated: normalizeWorkflowActivations(result.activated),
        reused: normalizeWorkflowActivations(result.reused),
      }))
    },
    deactivate(name, options = {}) {
      return operation<Record<string, unknown>>('workflow.deactivate', {
        name,
        ...(options.workRoot ? { work_root: options.workRoot } : {}),
        ...(options.triggerId ? { trigger_id: options.triggerId } : {}),
      }).then((result) => Array.isArray(result.cancelled) ? result.cancelled.map(String) : [])
    },
    listActivations(name, workRoot) {
      return operation<Record<string, unknown>>('workflow.activation.list', {
        name,
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then((result) => normalizeWorkflowActivations(result.activations))
    },
    objectInfo(nodeType) {
      return operation<Record<string, unknown>>('workflow.object_info', nodeType ? { node_type: nodeType } : {})
        .then((result) => normalizeWorkflowObjectInfo(result, nodeType))
    },
    enqueue(name, options = {}) {
      return operation<Record<string, unknown>>('workflow.queue.enqueue', buildWorkflowQueuePayload(name, options))
        .then((result) => normalizeWorkflowQueueItem(result.queue ?? result.item ?? result))
    },
    listQueue(options = {}) {
      return operation<Record<string, unknown>>('workflow.queue.list', buildWorkflowQueueQuery(options, true))
        .then((result) => normalizeWorkflowQueueItems(result.queue ?? result.items ?? result.queue_items))
    },
    historyQueue(options = {}) {
      return operation<Record<string, unknown>>('workflow.queue.history', buildWorkflowQueueQuery(options, false))
        .then((result) => normalizeWorkflowQueueItems(result.history ?? result.items ?? result.queue_items))
    },
    getQueue(queueId, runId) {
      return operation<Record<string, unknown>>('workflow.queue.get', {
        ...(queueId ? { queue_id: queueId } : {}),
        ...(runId ? { run_id: runId } : {}),
      }).then((result) => normalizeWorkflowQueueItem(result.queue ?? result.item ?? result))
    },
    clearQueue(options = {}) {
      return operation<Record<string, unknown>>('workflow.queue.clear', buildWorkflowQueueClearPayload(options))
        .then((result) => Number(result.count ?? result.cleared ?? 0) || 0)
    },
    cancelQueue(queueId, runId) {
      return operation<Record<string, unknown>>('workflow.queue.cancel', {
        ...(queueId ? { queue_id: queueId } : {}),
        ...(runId ? { run_id: runId } : {}),
      }).then((result) => normalizeWorkflowQueueItem(result.queue ?? result.item ?? result))
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
    importComfyUi(workflow, name, workRoot, expectedRevision) {
      return operation<WorkflowDocumentEnvelope>('workflow.import.comfyui', {
        workflow,
        name,
        ...expectedRevisionField(expectedRevision),
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then(requireWorkflowDocument('workflow.import.comfyui'))
    },
    exportComfyUi(name, version, workRoot) {
      return operation<{ workflow?: unknown }>('workflow.export.comfyui', {
        name,
        version,
        ...(workRoot ? { work_root: workRoot } : {}),
      }).then((result) => {
        if (!isRecord(result.workflow)) throw new Error('workflow.export.comfyui response is missing workflow')
        return result.workflow
      })
    },
    listHumanTasks(options = {}) {
      return operation<Record<string, unknown>>('workflow.human_task.list', {
        ...(options.workRoot ? { work_root: options.workRoot } : {}),
        ...(options.all ? { all: true } : {}),
        ...(options.status ? { status: options.status } : {}),
        ...(options.workflowId ? { workflow_id: options.workflowId } : {}),
        ...(options.workflowName ? { workflow_name: options.workflowName } : {}),
        ...(options.threadId ? { thread_id: options.threadId } : {}),
        ...(options.limit !== undefined ? { limit: options.limit } : {}),
        ...(options.includeAudit ? { include_audit: true } : {}),
      }).then((result) => normalizeWorkflowHumanTasks(result.tasks ?? result.pending ?? result.human_tasks))
    },
    getHumanTask(taskId, options = {}) {
      return operation<Record<string, unknown>>('workflow.human_task.get', {
        task_id: taskId,
        ...(options.workRoot ? { work_root: options.workRoot } : {}),
        ...(options.all ? { all: true } : {}),
      }).then((result) => {
        const task = normalizeWorkflowHumanTask(result.task)
        if (!task.task_id) throw new Error('workflow.human_task.get response is missing task')
        return task
      })
    },
    completeHumanTask(taskId, decision = '', payload = {}, options = {}) {
      return operation<Record<string, unknown>>('workflow.human_task.complete', {
        task_id: taskId,
        ...(decision ? { decision } : {}),
        payload,
        ...(options.workRoot ? { work_root: options.workRoot } : {}),
        ...(options.all ? { all: true } : {}),
      }).then((result) => {
        const task = normalizeWorkflowHumanTask(result.task)
        if (!task.task_id) throw new Error('workflow.human_task.complete response is missing task')
        return {
          task,
          run: isRecord(result.run) ? result.run : null,
          idempotent: result.idempotent === true,
          ...(typeof result.timed_out === 'boolean' ? { timed_out: result.timed_out } : {}),
        }
      })
    },
  }
}

type WorkflowDocumentEnvelope = {
  document?: WorkflowDocumentV2
  workflow?: WorkflowDef
}

type RawWorkflowRunResponse = {
  run?: RawWorkflowRunResult
  result?: RawWorkflowRunResult
  thread_id?: unknown
  threadId?: unknown
  run_id?: unknown
  runId?: unknown
  continuation?: unknown
  continuation_token?: unknown
  continuation_state?: unknown
  cache?: unknown
}

type RawWorkflowRunResult = Partial<WorkflowRunResult> & {
  status?: unknown
  node_states?: unknown
  nodeStates?: unknown
  values?: unknown
  error?: unknown
  run_id?: unknown
  runId?: unknown
  steps_remaining?: unknown
  stepsRemaining?: unknown
  started_at?: unknown
  startedAt?: unknown
  finished_at?: unknown
  finishedAt?: unknown
  continuation?: unknown
  continuation_token?: unknown
  continuation_state?: unknown
  cache?: unknown
}

/** Build the wire payload for both the modern continuation and legacy runner. */
export function buildWorkflowRunPayload(
  name: string,
  options: WorkflowRunOptions = {},
  includeContinuation = true,
): Record<string, unknown> {
  const continuation = options.continuation
  return {
    name,
    ...(options.workRoot ? { work_root: options.workRoot } : {}),
    ...(options.modelId ? { model_id: options.modelId } : {}),
    ...(options.permissions ? { permissions: options.permissions } : {}),
    ...(options.inputs ? { inputs: options.inputs } : {}),
    ...(options.maxSteps !== undefined ? { max_steps: options.maxSteps } : {}),
    ...(options.priorValues ? { prior_values: options.priorValues } : {}),
    ...(options.priorNodeStates ? { prior_node_states: serializeNodeStates(options.priorNodeStates) } : {}),
    ...(options.startNode ? { start_node: options.startNode } : {}),
    ...(options.singleNode ? { single_node: options.singleNode } : {}),
    ...(options.runId ? { run_id: options.runId } : {}),
    ...(options.threadId ? { thread_id: options.threadId } : {}),
    ...(includeContinuation && continuation?.token ? { continuation_token: continuation.token } : {}),
    ...(includeContinuation && continuation?.state !== undefined ? { continuation_state: continuation.state } : {}),
  }
}

/** Build the queue.enqueue wire payload using the same snake_case contract as the CLI. */
export function buildWorkflowQueuePayload(
  name: string,
  options: WorkflowQueueOptions = {},
): Record<string, unknown> {
  return {
    name,
    ...(options.workRoot ? { work_root: options.workRoot } : {}),
    ...(options.modelId ? { model_id: options.modelId } : {}),
    ...(options.inputs ? { inputs: options.inputs } : {}),
    ...(options.maxSteps !== undefined ? { max_steps: options.maxSteps } : {}),
    ...(options.startNode ? { start_node: options.startNode } : {}),
    ...(options.singleNode ? { single_node: options.singleNode } : {}),
    ...(options.priorValues ? { prior_values: options.priorValues } : {}),
    ...(options.priorNodeStates ? { prior_node_states: serializeNodeStates(options.priorNodeStates) } : {}),
    ...(options.threadId ? { thread_id: options.threadId } : {}),
    ...(options.runId ? { run_id: options.runId } : {}),
    ...(options.permissions || options.metadata ? {
      metadata: {
        ...(options.permissions ? { runtime_permissions: options.permissions } : {}),
        ...(options.metadata || {}),
      },
    } : {}),
  }
}

export function buildWorkflowQueueQuery(
  options: WorkflowQueueQuery = {},
  includeHistory = true,
): Record<string, unknown> {
  return {
    ...(options.workRoot ? { work_root: options.workRoot } : {}),
    ...(options.workflowId ? { workflow_id: options.workflowId } : {}),
    ...(options.name ? { name: options.name } : {}),
    ...(options.status ? { status: options.status } : {}),
    ...(options.limit !== undefined ? { limit: options.limit } : {}),
    ...(includeHistory ? { include_history: options.includeHistory ?? false } : {}),
    ...(!includeHistory && options.includeActive !== undefined ? { include_active: options.includeActive } : {}),
  }
}

export function buildWorkflowQueueClearPayload(options: WorkflowQueueClearOptions = {}): Record<string, unknown> {
  return {
    confirm: options.confirm === true,
    ...(options.all ? { all: true } : {}),
    ...(options.workRoot ? { work_root: options.workRoot } : {}),
    ...(options.workflowId ? { workflow_id: options.workflowId } : {}),
    ...(options.name ? { name: options.name } : {}),
  }
}

/** Normalize object-info envelopes and single-entry responses from old hosts. */
export function normalizeWorkflowObjectInfo(
  raw: unknown,
  requestedType = '',
): Record<string, WorkflowNodeSchema> {
  const value = raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, unknown>
    : {}
  const candidate = isRecord(value.object_info)
    ? value.object_info
    : isRecord(value.node_types)
      ? value.node_types
      : isRecord(value.schemas)
        ? value.schemas
        : value
  const looksLikeSchema = (item: unknown): item is Record<string, unknown> => {
    if (!isRecord(item)) return false
    return ['name', 'type_id', 'display_name', 'title', 'category', 'input', 'output', 'input_schema', 'output_schema'].some((key) => key in item)
  }
  if (requestedType && looksLikeSchema(candidate)) {
    return { [requestedType]: normalizeWorkflowNodeSchema(candidate, requestedType) }
  }
  return Object.entries(candidate).flatMap(([key, item]) => {
    if (!looksLikeSchema(item)) return []
    return [[key, normalizeWorkflowNodeSchema(item, key)] as [string, WorkflowNodeSchema]]
  }).reduce<Record<string, WorkflowNodeSchema>>((acc, [key, item]) => {
    acc[key] = item
    return acc
  }, {})
}

function normalizeWorkflowNodeSchema(raw: Record<string, unknown>, fallbackName: string): WorkflowNodeSchema {
  const name = String(raw.name ?? raw.type_id ?? fallbackName).trim() || fallbackName
  return {
    ...raw,
    name,
    type_id: String(raw.type_id ?? name),
    display_name: String(raw.display_name ?? raw.title ?? name),
    title: String(raw.title ?? raw.display_name ?? name),
    description: String(raw.description ?? ''),
    category: String(raw.category ?? 'workflow'),
    ...(isRecord(raw.input) ? { input: raw.input } : {}),
    ...(isRecord(raw.output) ? { output: raw.output } : {}),
  }
}

export function normalizeWorkflowQueueItem(raw: unknown): WorkflowQueueItem {
  const value = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {}
  const statusValue = String(value.status ?? 'queued').toLowerCase()
  const status: WorkflowQueueStatus = ['queued', 'running', 'completed', 'failed', 'cancelled', 'paused'].includes(statusValue)
    ? statusValue as WorkflowQueueStatus
    : 'queued'
  const queueId = String(value.queue_id ?? value.queueId ?? value.id ?? '').trim()
  const resultRaw = value.result
  const result = resultRaw && typeof resultRaw === 'object' && !Array.isArray(resultRaw)
    ? normalizeWorkflowRunResult(resultRaw as RawWorkflowRunResult)
    : null
  const priorStates = value.prior_node_states ?? value.priorNodeStates
  return {
    queue_id: queueId,
    id: queueId,
    workflow_id: String(value.workflow_id ?? value.workflowId ?? ''),
    workflow_name: String(value.workflow_name ?? value.workflowName ?? value.name ?? ''),
    work_root: String(value.work_root ?? value.workRoot ?? ''),
    thread_id: String(value.thread_id ?? value.threadId ?? ''),
    run_id: String(value.run_id ?? value.runId ?? ''),
    inputs: isRecord(value.inputs) ? value.inputs : {},
    status,
    priority: Number.isInteger(Number(value.priority)) ? Number(value.priority) : 0,
    created_at: nullableString(value.created_at ?? value.createdAt),
    updated_at: nullableString(value.updated_at ?? value.updatedAt),
    started_at: nullableString(value.started_at ?? value.startedAt),
    finished_at: nullableString(value.finished_at ?? value.finishedAt),
    max_steps: numberOrNull(value.max_steps ?? value.maxSteps),
    start_node: nullableString(value.start_node ?? value.startNode),
    single_node: nullableString(value.single_node ?? value.singleNode),
    prior_values: isRecord(value.prior_values ?? value.priorValues) ? (value.prior_values ?? value.priorValues) as Record<string, unknown> : {},
    prior_node_states: isRecord(priorStates)
      ? Object.fromEntries(Object.entries(priorStates).map(([nodeId, state]) => [nodeId, normalizeWorkflowNodeState(state, nodeId)]))
      : {},
    result,
    error: String(value.error ?? ''),
    metadata: isRecord(value.metadata) ? value.metadata : {},
  }
}

export function normalizeWorkflowQueueItems(raw: unknown): WorkflowQueueItem[] {
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item) => {
    const normalized = normalizeWorkflowQueueItem(item)
    return normalized.queue_id || normalized.run_id ? [normalized] : []
  })
}

function nullableString(value: unknown): string | null {
  if (value === undefined || value === null || value === '') return null
  return String(value)
}

function numberOrNull(value: unknown): number | null {
  if (value === undefined || value === null || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function expectedRevisionField(value: unknown): Record<string, number | string> {
  if (typeof value === 'number' && Number.isFinite(value)) return { expected_revision: value }
  if (typeof value === 'string' && /^\d+$/.test(value.trim())) return { expected_revision: value.trim() }
  return {}
}

function serializeNodeStates(states: Record<string, WorkflowNodeState>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(states).map(([nodeId, state]) => [nodeId, {
    ...state,
    node_id: state.node_id || nodeId,
  }]))
}

/** Accept only errors that indicate an old server cannot parse continuation fields. */
export function isContinuationContractUnsupported(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return /(?:unknown|unsupported|unrecognized|unexpected|not\s+supported|extra).*?(?:continuation|resume)|(?:continuation|resume).*?(?:unknown|unsupported|unrecognized|unexpected|not\s+supported|extra)/i.test(message)
}

/** Detect the structured and textual forms of a workflow revision conflict. */
export function isWorkflowRevisionConflict(error: unknown): boolean {
  const seen = new Set<unknown>()
  const visit = (value: unknown, depth: number): boolean => {
    if (depth > 3 || value === null || value === undefined || seen.has(value)) return false
    if (typeof value === 'object' || typeof value === 'function') seen.add(value)
    if (typeof value === 'number') return value === 409
    if (typeof value === 'string') {
      return /(?:revision\s+conflict|conflict.*revision|compare[-_ ]and[-_ ]swap|\b409\b)/i.test(value)
    }
    if (typeof value !== 'object') return false
    const record = value as Record<string, unknown>
    const code = record.code ?? record.status ?? record.statusCode ?? record.status_code
    if (code === 409 || String(code || '').toUpperCase() === 'REVISION_CONFLICT') return true
    return ['message', 'error', 'detail', 'data', 'cause'].some((key) => visit(record[key], depth + 1))
  }
  return visit(error, 0)
}

/**
 * Return true only when the host itself does not know an RPC operation.
 * Validation, network, authorization, and persistence errors must never
 * silently drop down to the legacy workflow representation.
 */
export function isWorkflowOperationUnsupported(error: unknown, method = ''): boolean {
  const seen = new Set<unknown>()
  const visit = (value: unknown, depth: number): boolean => {
    if (depth > 3 || value === null || value === undefined || seen.has(value)) return false
    if (typeof value === 'object' || typeof value === 'function') seen.add(value)
    if (typeof value === 'string') {
      const normalized = value.toLowerCase()
      const missingOperation = /operation(?:\s+['"`][^'"`]+['"`])?\s+is\s+not\s+registered|method\s+not\s+found|unknown\s+(?:rpc\s+)?(?:operation|method)/i.test(value)
      return missingOperation && (!method || normalized.includes(method.toLowerCase()) || /operation\s+is\s+not\s+registered|method\s+not\s+found/i.test(value))
    }
    if (typeof value === 'number') return value === -32601
    if (typeof value !== 'object') return false
    const record = value as Record<string, unknown>
    const code = record.code ?? record.status ?? record.statusCode ?? record.status_code
    if (code === -32601 || String(code || '').toUpperCase() === 'METHOD_NOT_FOUND') return true
    return ['message', 'error', 'detail', 'data', 'cause'].some((key) => visit(record[key], depth + 1))
  }
  return visit(error, 0)
}

export function normalizeWorkflowActivations(raw: unknown): WorkflowActivation[] {
  if (!Array.isArray(raw)) return []
  return raw.flatMap((candidate) => {
    if (!isRecord(candidate)) return []
    const workflowRevision = Number(candidate.workflow_revision ?? candidate.workflowRevision ?? 0)
    const runCount = Number(candidate.run_count ?? candidate.runCount ?? 0)
    const revision = Number(candidate.revision ?? 0)
    const rawMaxRuns = candidate.max_runs ?? candidate.maxRuns
    const maxRuns = rawMaxRuns === undefined || rawMaxRuns === null || rawMaxRuns === ''
      ? null
      : Number(rawMaxRuns)
    return [{
      id: String(candidate.id ?? ''),
      workflow_id: String(candidate.workflow_id ?? candidate.workflowId ?? ''),
      workflow_name: String(candidate.workflow_name ?? candidate.workflowName ?? ''),
      workflow_revision: Number.isFinite(workflowRevision) ? workflowRevision : 0,
      trigger_id: String(candidate.trigger_id ?? candidate.triggerId ?? ''),
      trigger_type: String(candidate.trigger_type ?? candidate.triggerType ?? ''),
      status: String(candidate.status ?? ''),
      next_run_at: (candidate.next_run_at ?? candidate.nextRunAt ?? null) as string | null,
      run_count: Number.isFinite(runCount) ? runCount : 0,
      max_runs: maxRuns === null || !Number.isFinite(maxRuns) ? null : maxRuns,
      last_error: String(candidate.last_error ?? candidate.lastError ?? ''),
      revision: Number.isFinite(revision) ? revision : 0,
    }]
  })
}

/** Normalize the secret-free human-task projection at the UI boundary. */
export function normalizeWorkflowHumanTask(raw: unknown): WorkflowHumanTask {
  const value = isRecord(raw) ? raw : {}
  const revision = Number(value.workflow_revision ?? value.revision ?? 0)
  const audit = Array.isArray(value.audit)
    ? value.audit.flatMap((candidate) => {
        if (!isRecord(candidate)) return []
        const sequence = Number(candidate.sequence ?? 0)
        return [{
          event_id: String(candidate.event_id ?? candidate.eventId ?? ''),
          sequence: Number.isFinite(sequence) ? sequence : 0,
          kind: String(candidate.kind ?? ''),
          occurred_at: (candidate.occurred_at ?? candidate.occurredAt ?? null) as string | null,
          workflow_id: String(candidate.workflow_id ?? candidate.workflowId ?? ''),
          workflow_revision: Number(candidate.workflow_revision ?? candidate.workflowRevision ?? 0) || 0,
          node_id: String(candidate.node_id ?? candidate.nodeId ?? ''),
          attempt_id: String(candidate.attempt_id ?? candidate.attemptId ?? ''),
          payload: isRecord(candidate.payload) ? candidate.payload : {},
        }]
      })
    : []
  return {
    task_id: String(value.task_id ?? value.taskId ?? value.id ?? ''),
    id: String(value.id ?? value.task_id ?? value.taskId ?? ''),
    status: String(value.status ?? 'pending'),
    run_id: String(value.run_id ?? value.runId ?? value.run ?? ''),
    run: String(value.run ?? value.run_id ?? value.runId ?? ''),
    thread_id: String(value.thread_id ?? value.threadId ?? value.thread ?? ''),
    thread: String(value.thread ?? value.thread_id ?? value.threadId ?? ''),
    workflow_id: String(value.workflow_id ?? value.workflowId ?? ''),
    workflow_name: String(value.workflow_name ?? value.workflowName ?? ''),
    workflow: String(value.workflow ?? value.workflow_id ?? value.workflowId ?? value.workflow_name ?? value.workflowName ?? ''),
    workflow_revision: Number.isFinite(revision) ? revision : 0,
    revision: Number.isFinite(revision) ? revision : 0,
    node_id: String(value.node_id ?? value.nodeId ?? value.node ?? ''),
    node: String(value.node ?? value.node_id ?? value.nodeId ?? ''),
    kind: String(value.kind ?? 'wait_event'),
    title: String(value.title ?? value.node ?? value.node_id ?? ''),
    assignee: value.assignee === null || value.assignee === undefined ? null : String(value.assignee),
    group: value.group === null || value.group === undefined ? null : String(value.group),
    form: value.form ?? {},
    due_at: (value.due_at ?? value.dueAt ?? null) as string | null,
    event_type: String(value.event_type ?? value.eventType ?? 'event'),
    created_at: (value.created_at ?? value.createdAt ?? null) as string | null,
    completed_at: (value.completed_at ?? value.completedAt ?? null) as string | null,
    outcome: isRecord(value.outcome) ? value.outcome : null,
    work_root: String(value.work_root ?? value.workRoot ?? ''),
    ...(audit.length ? { audit } : {}),
  }
}

export function normalizeWorkflowHumanTasks(raw: unknown): WorkflowHumanTask[] {
  if (!Array.isArray(raw)) return []
  return raw.map(normalizeWorkflowHumanTask).filter((task) => Boolean(task.task_id))
}

export function normalizeWorkflowNodeState(raw: unknown, nodeId = ''): WorkflowNodeState {
  const value = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const attempts = Number(value.attempts ?? value.attempt_count ?? 0)
  const cacheStatus = value.cache_status ?? value.cacheStatus ?? (typeof value.cache === 'string' ? value.cache : undefined)
  const cacheKey = value.cache_key ?? value.cacheKey
  const rawDuration = value.duration_ms ?? value.durationMs ?? value.duration
  const durationSeconds = Number(value.duration_seconds ?? value.durationSeconds ?? NaN)
  const duration = rawDuration !== undefined
    ? Number(rawDuration)
    : Number.isFinite(durationSeconds) ? durationSeconds * 1000 : NaN
  const input = value.input ?? value.inputs ?? value.input_values ?? value.inputValues
  const toolCalls = value.tool_calls ?? value.toolCalls ?? value.tools
  const logs = value.logs ?? value.log ?? value.messages
  const audit = value.audit ?? value.audit_events ?? value.auditEvents
  return {
    node_id: String(value.node_id ?? value.nodeId ?? nodeId),
    status: normalizeNodeStateStatus(value.status),
    ...(Object.prototype.hasOwnProperty.call(value, 'input')
      || Object.prototype.hasOwnProperty.call(value, 'inputs')
      || Object.prototype.hasOwnProperty.call(value, 'input_values')
      || Object.prototype.hasOwnProperty.call(value, 'inputValues')
      ? { input }
      : {}),
    ...(Object.prototype.hasOwnProperty.call(value, 'output') ? { output: value.output } : {}),
    ...(value.error ? { error: String(value.error) } : {}),
    attempts: Number.isFinite(attempts) ? Math.max(0, attempts) : 0,
    ...(typeof value.attempt_id === 'string' || typeof value.attemptId === 'string'
      ? { attempt_id: String(value.attempt_id ?? value.attemptId) }
      : {}),
    ...(Number.isFinite(duration) && duration >= 0 ? { duration_ms: duration } : {}),
    ...(toolCalls !== undefined && toolCalls !== null ? { tool_calls: toolCalls } : {}),
    ...(logs !== undefined && logs !== null ? { logs } : {}),
    ...(audit !== undefined && audit !== null ? { audit } : {}),
    ...(cacheStatus !== undefined ? { cache_status: String(cacheStatus) } : {}),
    ...(cacheKey !== undefined && cacheKey !== null ? { cache_key: String(cacheKey) } : {}),
    started_at: value.started_at === undefined && value.startedAt === undefined
      ? null
      : (value.started_at ?? value.startedAt ?? null) as string | null,
    finished_at: value.finished_at === undefined && value.finishedAt === undefined
      ? null
      : (value.finished_at ?? value.finishedAt ?? null) as string | null,
  }
}

export function normalizeWorkflowRunResult(raw: RawWorkflowRunResult): WorkflowRunResult {
  const statesRaw = raw.node_states ?? raw.nodeStates
  const states = statesRaw && typeof statesRaw === 'object'
    ? Object.fromEntries(Object.entries(statesRaw as Record<string, unknown>).map(([nodeId, state]) => [nodeId, normalizeWorkflowNodeState(state, nodeId)]))
    : {}
  const values = raw.values && typeof raw.values === 'object' ? raw.values as Record<string, unknown> : {}
  const cache = normalizeWorkflowCache(raw.cache)
  // A few older runners only put cache facts on node_states. Preserve those
  // facts in the run-level map as well so callers have one stable surface.
  for (const [nodeId, state] of Object.entries(states)) {
    if (cache[nodeId] || (state.cache_status === undefined && state.cache_key === undefined)) continue
    const status = state.cache_status
    cache[nodeId] = {
      ...(status !== undefined ? { status } : {}),
      ...(state.cache_key !== undefined ? { key: state.cache_key } : {}),
      ...(status === 'hit' ? { hit: true, miss: false } : {}),
      ...(status === 'miss' ? { hit: false, miss: true } : {}),
    }
  }
  const stepsRemaining = Number(raw.steps_remaining ?? raw.stepsRemaining ?? 0)
  return {
    status: normalizeWorkflowRunStatus(raw.status),
    ...(Object.prototype.hasOwnProperty.call(raw, 'output') ? { output: raw.output } : { output: null }),
    node_states: states,
    values,
    cache,
    error: raw.error ? String(raw.error) : '',
    run_id: String(raw.run_id ?? raw.runId ?? ''),
    steps_remaining: Number.isFinite(stepsRemaining) ? Math.max(0, stepsRemaining) : 0,
    started_at: (raw.started_at ?? raw.startedAt ?? null) as string | null,
    finished_at: (raw.finished_at ?? raw.finishedAt ?? null) as string | null,
  }
}

/** Normalize cache facts without dropping hit/miss/key fields from the wire. */
export function normalizeWorkflowCache(raw: unknown): Record<string, WorkflowCacheFact> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
  return Object.fromEntries(Object.entries(raw as Record<string, unknown>).flatMap(([nodeId, candidate]) => {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return []
    const value = candidate as Record<string, unknown>
    const statusValue = value.status ?? value.cache_status ?? value.cacheStatus
    const status = statusValue === undefined || statusValue === null ? undefined : String(statusValue)
    const keyValue = value.key ?? value.cache_key ?? value.cacheKey
    const key = keyValue === undefined || keyValue === null ? undefined : String(keyValue)
    const hit = typeof value.hit === 'boolean'
      ? value.hit
      : typeof value.cache_hit === 'boolean'
        ? value.cache_hit
        : status === 'hit' ? true : status === 'miss' ? false : undefined
    const miss = typeof value.miss === 'boolean'
      ? value.miss
      : typeof value.cache_miss === 'boolean'
        ? value.cache_miss
        : status === 'miss' ? true : status === 'hit' ? false : undefined
    return [[nodeId, {
      ...value,
      ...(status !== undefined ? { status } : {}),
      ...(key !== undefined ? { key } : {}),
      ...(hit !== undefined ? { hit } : {}),
      ...(miss !== undefined ? { miss } : {}),
    }]]
  })) as Record<string, WorkflowCacheFact>
}

export function normalizeWorkflowRunResponse(result: RawWorkflowRunResponse): WorkflowRunResponse {
  const rawRun = result.run ?? result.result
  if (!rawRun) throw new Error('workflow.run response is missing run')
  const run = normalizeWorkflowRunResult(rawRun)
  const continuation = normalizeContinuation(result, rawRun)
  return {
    run,
    thread_id: String(result.thread_id ?? result.threadId ?? ''),
    run_id: String(result.run_id ?? result.runId ?? run.run_id ?? ''),
    ...(continuation ? { continuation } : {}),
  }
}

function normalizeContinuation(result: RawWorkflowRunResponse, run: RawWorkflowRunResult): WorkflowContinuationState | undefined {
  const raw = result.continuation ?? run.continuation
  const value = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const token = String(value.token ?? value.continuation_token ?? result.continuation_token ?? run.continuation_token ?? '').trim()
  const state = value.state ?? value.continuation_state ?? result.continuation_state ?? run.continuation_state
  const runId = String(value.run_id ?? value.runId ?? '').trim()
  if (!token && state === undefined && !runId) return undefined
  return {
    ...(token ? { token } : {}),
    ...(state !== undefined ? { state } : {}),
    ...(runId ? { runId } : {}),
  }
}

function requireWorkflow(method: string) {
  return (result: { workflow?: WorkflowDef }): WorkflowDef => {
    if (!result.workflow) throw new Error(`${method} response is missing workflow`)
    return result.workflow
  }
}

function requireWorkflowDocument(method: string) {
  return (result: WorkflowDocumentEnvelope): WorkflowDef => {
    if (!result.document) throw new Error(`${method} response is missing document`)
    return workflowDocumentToDefinition(result.document)
  }
}
