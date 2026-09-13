import type {
  WorkflowDef,
  WorkflowDocumentCanvas,
  WorkflowDocumentInterfaceInput,
  WorkflowDocumentInterfaceOutput,
  WorkflowDocumentLink,
  WorkflowDocumentNode,
  WorkflowDocumentPort,
  WorkflowDocumentV2,
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeState,
  WorkflowPort,
  WorkflowNodeKind,
} from './types'
import { normalizeCanvasElement, type WorkflowCanvasElement } from './canvas'
import { workflowNodeKindForTypeId } from './catalog'

export const WORKFLOW_DOCUMENT_FORMAT = 'lamtools.workflow' as const
export const WORKFLOW_DOCUMENT_VERSION = 2 as const

/** Return true only for the canonical, versioned editor document envelope. */
export function isWorkflowDocumentV2(value: unknown): value is WorkflowDocumentV2 {
  return Boolean(
    value
    && typeof value === 'object'
    && (value as Record<string, unknown>).format === WORKFLOW_DOCUMENT_FORMAT
    && (value as Record<string, unknown>).version === WORKFLOW_DOCUMENT_VERSION,
  )
}

/**
 * Convert the editor's convenient WorkflowDef projection to the canonical
 * V2 document.  The conversion is intentionally pure: UI-only positions and
 * decorations live under canvas, while executable graph semantics live under
 * graph/interface.  This mirrors ComfyUI's graph-vs-prompt split and keeps
 * Agent/tool consumers independent of canvas details.
 */
export function workflowDefinitionToDocument(definition: WorkflowDef): WorkflowDocumentV2 {
  const portIds = new Map<string, string>()
  const usedPortIds = new Set<string>()
  const portIdFor = (node: WorkflowNode, port: WorkflowPort, index: number): string => {
    const key = `${node.id}:${port.direction}:${port.name}:${index}`
    const existing = String(port.id || '').trim()
    let id = existing || `port_${stableHash(`${definition.id}:${key}`)}`
    let serial = 1
    while (usedPortIds.has(id)) id = `${existing || `port_${stableHash(`${definition.id}:${key}`)}`}_${serial++}`
    usedPortIds.add(id)
    portIds.set(`${node.id}:${port.direction}:${port.name}`, id)
    return id
  }

  const nodes: WorkflowDocumentNode[] = definition.nodes.map((node) => {
    const ports: WorkflowDocumentPort[] = node.ports.map((port, index) => ({
      id: portIdFor(node, port, index),
      name: port.name,
      direction: port.direction,
      data_type: port.type || 'any',
      description: port.description || '',
      required: Boolean(port.required),
      lazy: Boolean(port.lazy),
      ...(port.value !== undefined ? { default: cloneUnknown(port.value) } : {}),
    }))
    const rawConfig = cloneRecord(node.config)
    const rawExecution = isRecord(rawConfig.execution) ? cloneRecord(rawConfig.execution) : {}
    delete rawConfig.execution
    const configError = rawConfig.on_error
    delete rawConfig.on_error
    const execution = {
      enabled: rawExecution.enabled !== false,
      schema_only: rawExecution.schema_only === true,
      cache: String(rawExecution.cache || 'auto'),
      on_error: isRecord(rawExecution.on_error)
        ? cloneRecord(rawExecution.on_error)
        : isRecord(configError) ? cloneRecord(configError) : { strategy: 'abort' },
      permissions: Array.isArray(rawExecution.permissions)
        ? rawExecution.permissions.map((item) => String(item))
        : [],
    }
    return {
      id: node.id,
      type: {
        id: String(node.type_id || node.kind || 'command'),
        version: Math.max(1, Number(node.type_version) || 1),
      },
      title: node.title || node.id,
      ports,
      params: rawConfig,
      execution,
    }
  })

  const links: WorkflowDocumentLink[] = definition.edges.map((edge) => ({
    id: edge.id,
    source: {
      node_id: edge.source,
      port_id: portIds.get(`${edge.source}:out:${edge.source_port}`) || edge.source_port,
    },
    target: {
      node_id: edge.target,
      port_id: portIds.get(`${edge.target}:in:${edge.target_port}`) || edge.target_port,
    },
    ...(edge.transform ? { transform: edge.transform } : {}),
    ...(edge.condition ? { condition: edge.condition } : {}),
  }))

  const interfaceInputs: WorkflowDocumentInterfaceInput[] = definition.input_params.map((param, index) => {
    const input: WorkflowDocumentInterfaceInput = {
      id: `input_${stableHash(`${definition.id}:${param.name}:${index}`)}`,
      name: param.name,
      data_type: param.type || 'any',
      description: param.description || '',
      required: Boolean(param.required),
      ...(param.default !== undefined ? { default: cloneUnknown(param.default) } : {}),
    }
    const separator = param.name.lastIndexOf('.')
    if (separator > 0) {
      const nodeId = param.name.slice(0, separator)
      const portName = param.name.slice(separator + 1)
      const portId = portIds.get(`${nodeId}:in:${portName}`)
      if (portId) input.target = { node_id: nodeId, port_id: portId }
    }
    return input
  })

  const output = resolveOutputPort(definition, portIds)
  const interfaceOutputs: WorkflowDocumentInterfaceOutput[] = output
    ? [{
      id: `output_${stableHash(`${definition.id}:${output.nodeId}:${output.portId}`)}`,
      name: output.name,
      data_type: output.type,
      description: '',
      source: { node_id: output.nodeId, port_id: output.portId },
    }]
    : []

  const previousDocument = isWorkflowDocumentV2(definition.document) ? definition.document : null
  const previousCanvas = previousDocument
    ? cloneCanvas(previousDocument.canvas)
    : emptyCanvas()
  const nodeViews = { ...previousCanvas.node_views }
  for (const node of definition.nodes) {
    const nextView: Record<string, unknown> = {
      ...(nodeViews[node.id] || {}),
      position: { x: Number(node.position?.x) || 0, y: Number(node.position?.y) || 0 },
    }
    if (node.parent_id !== undefined && node.parent_id !== null && String(node.parent_id).trim()) {
      nextView.parent_id = String(node.parent_id).trim()
      // Canonical V2 has only the snake_case spelling.
      delete nextView.parentId
    } else {
      // The definition projection is authoritative.  Remove stale values
      // from a prior document rather than reviving a cleared parent.
      delete nextView.parent_id
      delete nextView.parentId
    }
    nodeViews[node.id] = nextView
  }
  const canvas = canvasFromElements(definition.canvas_elements, { ...previousCanvas, node_views: nodeViews })

  return {
    format: WORKFLOW_DOCUMENT_FORMAT,
    version: WORKFLOW_DOCUMENT_VERSION,
    resource: {
      id: definition.id,
      name: definition.name,
      description: definition.description || '',
      work_root: definition.work_root || '',
      revision: numericRevision(definition.revision),
      created_at: definition.created_at || new Date().toISOString(),
      updated_at: definition.updated_at || new Date().toISOString(),
    },
    graph: { nodes, links },
    interface: { inputs: interfaceInputs, outputs: interfaceOutputs },
    exposure: { enabled: definition.exposed === true, tool_name: definition.tool_name || '' },
    canvas,
    triggers: cloneUnknown(definition.triggers ?? previousDocument?.triggers ?? []),
    policies: cloneRecord(definition.policies ?? previousDocument?.policies ?? {}),
  }
}

/** Convert a canonical V2 document back to the legacy runtime/UI projection. */
export function workflowDocumentToDefinition(document: WorkflowDocumentV2, fallback?: WorkflowDef): WorkflowDef {
  if (!isWorkflowDocumentV2(document)) {
    if (fallback) return cloneWorkflowDefinition(fallback)
    throw new Error('expected lamtools.workflow V2 document')
  }
  const portNames = new Map<string, WorkflowDocumentPort>()
  const nodes = document.graph.nodes.map((node) => {
    const view = document.canvas.node_views[node.id]
    const position = isRecord(view?.position) ? view.position : view
    const ports = node.ports.map((port) => {
      portNames.set(`${node.id}:${port.id}`, port)
      return {
        id: port.id,
        name: port.name,
        type: port.data_type || 'any',
        direction: port.direction,
        description: port.description || '',
        required: port.required,
        lazy: port.lazy,
        ...(Object.prototype.hasOwnProperty.call(port, 'default') ? { value: cloneUnknown(port.default) } : {}),
      }
    })
    const config = cloneRecord(node.params)
    config.execution = cloneRecord(node.execution)
    config.on_error = cloneRecord(node.execution.on_error)
    const parentId = isRecord(view)
      ? (Object.prototype.hasOwnProperty.call(view, 'parent_id') ? view.parent_id : view.parentId)
      : undefined
    return {
      id: node.id,
      // Keep the registry type id visible to the editor. Unknown/custom types
      // are not silently projected into `command`; the runtime can resolve
      // them through its trusted registry on the next execution.
      kind: workflowNodeKindForTypeId(node.type.id) as WorkflowNodeKind,
      type_id: node.type.id,
      type_version: node.type.version,
      title: node.title || node.id,
      config,
      ports,
      position: {
        x: numberAt(position, 'x'),
        y: numberAt(position, 'y'),
      },
      ...(parentId !== undefined && parentId !== null && String(parentId).trim()
        ? { parent_id: String(parentId).trim() }
        : {}),
    }
  })
  const edges = document.graph.links.map((link) => ({
    id: link.id,
    source: link.source.node_id,
    source_port: portNames.get(`${link.source.node_id}:${link.source.port_id}`)?.name || link.source.port_id,
    source_port_id: link.source.port_id,
    target: link.target.node_id,
    target_port: portNames.get(`${link.target.node_id}:${link.target.port_id}`)?.name || link.target.port_id,
    target_port_id: link.target.port_id,
    ...(link.transform ? { transform: link.transform } : {}),
    ...(link.condition ? { condition: link.condition } : {}),
  }))
  const outputs = document.interface.outputs || []
  const output = outputs[0]
  const outputPort = output
    ? `${output.source.node_id}.${portNames.get(`${output.source.node_id}:${output.source.port_id}`)?.name || output.source.port_id}`
    : ''
  const canvasElements = canvasElementsFromDocument(document.canvas)
  return {
    ...(fallback ? cloneWorkflowDefinition(fallback) : {}),
    id: document.resource.id,
    name: document.resource.name,
    description: document.resource.description || '',
    nodes,
    edges,
    input_params: (document.interface.inputs || []).map((item) => ({
      name: item.name,
      type: item.data_type || 'any',
      description: item.description || '',
      required: item.required === true,
      ...(Object.prototype.hasOwnProperty.call(item, 'default') ? { default: cloneUnknown(item.default) } : {}),
    })),
    output_port: outputPort,
    exposed: document.exposure.enabled === true,
    tool_name: document.exposure.tool_name || '',
    work_root: document.resource.work_root || '',
    map: fallback?.map || '',
    created_at: document.resource.created_at || fallback?.created_at || new Date().toISOString(),
    updated_at: document.resource.updated_at || fallback?.updated_at || new Date().toISOString(),
    revision: document.resource.revision,
    triggers: cloneUnknown(document.triggers || []),
    policies: cloneRecord(document.policies || {}),
    canvas_elements: canvasElements,
    document: cloneWorkflowDefinitionDocument(document),
  }
}

function resolveOutputPort(definition: WorkflowDef, portIds: Map<string, string>): { nodeId: string; portId: string; name: string; type: string } | null {
  const raw = String(definition.output_port || '')
  const separator = raw.indexOf('.')
  const nodeId = separator > 0 ? raw.slice(0, separator) : raw
  const portName = separator > 0 ? raw.slice(separator + 1) : ''
  const node = definition.nodes.find((item) => item.id === nodeId)
  if (!node) return null
  const port = node.ports.find((item) => item.direction === 'out' && (!portName || item.name === portName))
  if (!port) return null
  return { nodeId, portId: portIds.get(`${node.id}:out:${port.name}`) || port.id || port.name, name: port.name || 'result', type: port.type || 'any' }
}

function canvasFromElements(elements: WorkflowCanvasElement[] | undefined, base: WorkflowDocumentCanvas): WorkflowDocumentCanvas {
  if (!elements?.length) return base
  const groups = [...base.groups]
  const reroutes = [...base.reroutes]
  const annotations = [...base.annotations]
  const upsert = (target: Array<Record<string, unknown>>, element: WorkflowCanvasElement, fallbackKind: string): void => {
    const value: Record<string, unknown> = {
      id: element.id,
      title: element.title,
      text: element.text,
      position: { ...element.position },
      width: element.width,
      height: element.height,
      ...(fallbackKind === 'reroute' ? {} : { kind: element.kind }),
      ...(element.color ? { color: element.color } : {}),
      ...(element.parent_id ? { parent_id: element.parent_id } : {}),
      ...(element.collapsed !== undefined ? { collapsed: element.collapsed } : {}),
      ...(element.z_index !== undefined ? { z_index: element.z_index } : {}),
      ...(element.data ? { data: cloneRecord(element.data) } : {}),
    }
    const index = target.findIndex((item, itemIndex) => (
      normalizeCanvasElement({ ...item, kind: item.kind || fallbackKind }, `${fallbackKind}-${itemIndex + 1}`)?.id === element.id
    ))
    if (index >= 0) target[index] = { ...target[index], ...value }
    else target.push(value)
  }
  for (const element of elements) {
    if (element.kind === 'group' || element.kind === 'frame') upsert(groups, element, 'group')
    else if (element.kind === 'reroute') upsert(reroutes, element, 'reroute')
    else upsert(annotations, element, 'annotation')
  }
  return { ...base, groups, reroutes, annotations }
}

function canvasElementsFromDocument(canvas: WorkflowDocumentCanvas): WorkflowCanvasElement[] {
  const raw: Array<[Record<string, unknown>, string]> = [
    ...(canvas.groups || []).map((item, index) => [{ ...item, kind: item.kind || 'group' }, `group-${index + 1}`] as [Record<string, unknown>, string]),
    ...(canvas.reroutes || []).map((item, index) => [{ ...item, kind: 'reroute' }, `reroute-${index + 1}`] as [Record<string, unknown>, string]),
    ...(canvas.annotations || []).map((item, index) => [{ ...item, kind: item.kind || 'note' }, `annotation-${index + 1}`] as [Record<string, unknown>, string]),
  ]
  return raw.flatMap(([item, key]) => {
    const normalized = normalizeCanvasElement(item, key)
    return normalized ? [normalized] : []
  })
}

function emptyCanvas(): WorkflowDocumentCanvas {
  return { viewport: { x: 0, y: 0, zoom: 1 }, node_views: {}, groups: [], reroutes: [], annotations: [] }
}

function cloneCanvas(value: WorkflowDocumentCanvas): WorkflowDocumentCanvas {
  return {
    viewport: { x: numberAt(value?.viewport, 'x'), y: numberAt(value?.viewport, 'y'), zoom: numberAt(value?.viewport, 'zoom', 1) },
    node_views: cloneRecord(value?.node_views),
    groups: Array.isArray(value?.groups) ? value.groups.map((item) => cloneRecord(item)) : [],
    reroutes: Array.isArray(value?.reroutes) ? value.reroutes.map((item) => cloneRecord(item)) : [],
    annotations: Array.isArray(value?.annotations) ? value.annotations.map((item) => cloneRecord(item)) : [],
  }
}

function cloneWorkflowDefinitionDocument(document: WorkflowDocumentV2): WorkflowDocumentV2 {
  return JSON.parse(JSON.stringify(document)) as WorkflowDocumentV2
}

function cloneUnknown<T>(value: T): T {
  try { return JSON.parse(JSON.stringify(value)) as T } catch { return value }
}

function cloneRecord(value: unknown): Record<string, any> {
  return isRecord(value) ? cloneUnknown(value) : {}
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function numberAt(value: unknown, key: string, fallback = 0): number {
  const result = isRecord(value) ? Number(value[key]) : Number.NaN
  return Number.isFinite(result) ? result : fallback
}

function numericRevision(value: unknown): number {
  const result = Number(value)
  return Number.isFinite(result) && result >= 0 ? Math.floor(result) : 0
}

function stableHash(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

/**
 * Revision metadata supplied by the workflow store.
 *
 * The backend currently exposes a numeric `revision`, while older workflow
 * files only have `updated_at`. Keeping this adapter deliberately loose lets
 * the editor participate in optimistic concurrency without making legacy
 * files unreadable.
 */
export interface WorkflowRevision {
  value?: number | string
  updatedAt?: string
}

export interface WorkflowSaveError {
  kind: 'save-error'
  message: string
  retryable: boolean
  cause?: unknown
}

export interface WorkflowDocumentConflict {
  kind: 'conflict'
  message: string
  local: WorkflowDef
  remote: WorkflowDef
  localRevision: WorkflowRevision
  remoteRevision: WorkflowRevision
}

export interface WorkflowDocumentCommand {
  id: string
  label: string
  before: WorkflowDef
  after: WorkflowDef
}

export interface WorkflowDocumentSnapshot {
  definition: WorkflowDef
  revision: WorkflowRevision
  dirty: boolean
  saveError: WorkflowSaveError | null
  conflict: WorkflowDocumentConflict | null
  canUndo: boolean
  canRedo: boolean
}

export interface WorkflowDocumentUpdateOptions {
  label?: string
  /** Runtime updates are intentionally ignored by the command history. */
  origin?: 'user' | 'runtime' | 'remote'
}

export interface WorkflowDocumentController {
  snapshot(): WorkflowDocumentSnapshot
  update(definition: WorkflowDef, options?: WorkflowDocumentUpdateOptions): boolean
  undo(): WorkflowDef | null
  redo(): WorkflowDef | null
  markSaved(definition?: WorkflowDef, revision?: WorkflowRevision): void
  markSaveError(error: unknown, retryable?: boolean): void
  clearSaveError(): void
  markConflict(remote: WorkflowDef, message?: string): void
  acceptRemote(remote: WorkflowDef): void
  /** Keep local edits while rebasing the expected revision onto remote. */
  keepLocalAfterConflict(): boolean
  subscribe(listener: (snapshot: WorkflowDocumentSnapshot) => void): () => void
}

const MAX_HISTORY = 100

/** A JSON-safe clone for the plain workflow document contract. */
export function cloneWorkflowDefinition(definition: WorkflowDef): WorkflowDef {
  return JSON.parse(JSON.stringify(definition)) as WorkflowDef
}

/** Stable enough for JSON workflow documents and independent of object key order. */
export function workflowDefinitionFingerprint(definition: WorkflowDef): string {
  return stableStringify(definition)
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  const record = value as Record<string, unknown>
  return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(',')}}`
}

function revisionOf(definition: WorkflowDef): WorkflowRevision {
  return {
    ...(definition.revision !== undefined ? { value: definition.revision } : {}),
    ...(definition.updated_at ? { updatedAt: definition.updated_at } : {}),
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  if (error && typeof error === 'object' && 'message' in error) return String((error as { message?: unknown }).message || error)
  return String(error)
}

function notify(listeners: Set<(snapshot: WorkflowDocumentSnapshot) => void>, snapshot: WorkflowDocumentSnapshot): void {
  for (const listener of listeners) listener(snapshot)
}

/**
 * Create the command/document layer used by the workflow editor.
 *
 * It is intentionally framework-free so command semantics can be verified by
 * direct Vitest tests and reused by a future non-Vue surface. Every user
 * update is immutable, undoable, and marked dirty until `markSaved` succeeds.
 */
export function createWorkflowDocument(initial: WorkflowDef): WorkflowDocumentController {
  let current = cloneWorkflowDefinition(initial)
  let savedFingerprint = workflowDefinitionFingerprint(current)
  let revision = revisionOf(current)
  let saveError: WorkflowSaveError | null = null
  let conflict: WorkflowDocumentConflict | null = null
  const undoStack: WorkflowDocumentCommand[] = []
  const redoStack: WorkflowDocumentCommand[] = []
  const listeners = new Set<(snapshot: WorkflowDocumentSnapshot) => void>()

  function snapshot(): WorkflowDocumentSnapshot {
    return {
      definition: cloneWorkflowDefinition(current),
      revision: { ...revision },
      dirty: workflowDefinitionFingerprint(current) !== savedFingerprint,
      saveError,
      conflict,
      canUndo: undoStack.length > 0,
      canRedo: redoStack.length > 0,
    }
  }

  function publish(): void {
    notify(listeners, snapshot())
  }

  function update(definition: WorkflowDef, options: WorkflowDocumentUpdateOptions = {}): boolean {
    // Runtime projections must never become document commands or trigger an
    // autosave. Remote updates go through acceptRemote so conflicts are not
    // silently overwritten.
    if (options.origin === 'runtime' || options.origin === 'remote') return false
    const next = cloneWorkflowDefinition(definition)
    if (workflowDefinitionFingerprint(next) === workflowDefinitionFingerprint(current)) return false
    undoStack.push({
      id: `workflow-command-${Date.now()}-${undoStack.length}`,
      label: options.label || '编辑工作流',
      before: cloneWorkflowDefinition(current),
      after: next,
    })
    if (undoStack.length > MAX_HISTORY) undoStack.shift()
    redoStack.length = 0
    current = next
    conflict = null
    saveError = null
    publish()
    return true
  }

  function undo(): WorkflowDef | null {
    const command = undoStack.pop()
    if (!command) return null
    redoStack.push(command)
    current = cloneWorkflowDefinition(command.before)
    saveError = null
    conflict = null
    publish()
    return cloneWorkflowDefinition(current)
  }

  function redo(): WorkflowDef | null {
    const command = redoStack.pop()
    if (!command) return null
    undoStack.push(command)
    current = cloneWorkflowDefinition(command.after)
    saveError = null
    conflict = null
    publish()
    return cloneWorkflowDefinition(current)
  }

  function markSaved(definition = current, nextRevision = revisionOf(definition)): void {
    current = cloneWorkflowDefinition(definition)
    savedFingerprint = workflowDefinitionFingerprint(current)
    revision = { ...nextRevision }
    saveError = null
    conflict = null
    publish()
  }

  function markSaveError(error: unknown, retryable = true): void {
    saveError = {
      kind: 'save-error',
      message: errorMessage(error),
      retryable,
      cause: error,
    }
    publish()
  }

  function clearSaveError(): void {
    if (!saveError) return
    saveError = null
    publish()
  }

  function markConflict(remote: WorkflowDef, message = '工作流已被其他来源修改，请选择保留本地或远端版本。'): void {
    const remoteCopy = cloneWorkflowDefinition(remote)
    conflict = {
      kind: 'conflict',
      message,
      local: cloneWorkflowDefinition(current),
      remote: remoteCopy,
      localRevision: { ...revision },
      remoteRevision: revisionOf(remoteCopy),
    }
    publish()
  }

  function acceptRemote(remote: WorkflowDef): void {
    const remoteCopy = cloneWorkflowDefinition(remote)
    current = remoteCopy
    savedFingerprint = workflowDefinitionFingerprint(current)
    revision = revisionOf(current)
    conflict = null
    saveError = null
    // A remote document becomes the new baseline; local undo cannot replay
    // commands against a different graph identity.
    undoStack.length = 0
    redoStack.length = 0
    publish()
  }

  function keepLocalAfterConflict(): boolean {
    if (!conflict) return false
    // Preserve the local document and its dirty baseline. Only the expected
    // revision moves to the remote version so the next save is an explicit
    // compare-and-swap retry rather than an unconditional overwrite.
    const remoteRevision = { ...conflict.remoteRevision }
    revision = remoteRevision
    // `WorkflowApi.save` derives its default expected_revision from the
    // definition. Keep the rebased value on both layers so a retry cannot
    // accidentally send the stale local revision. Legacy documents may have
    // no numeric revision; in that case remove the old value rather than
    // preserving a revision the remote document does not advertise.
    const rebasedDefinition = cloneWorkflowDefinition(current)
    if (remoteRevision.value === undefined) delete rebasedDefinition.revision
    else rebasedDefinition.revision = remoteRevision.value
    current = rebasedDefinition
    conflict = null
    saveError = null
    publish()
    return true
  }

  return {
    snapshot,
    update,
    undo,
    redo,
    markSaved,
    markSaveError,
    clearSaveError,
    markConflict,
    acceptRemote,
    keepLocalAfterConflict,
    subscribe(listener) {
      listeners.add(listener)
      listener(snapshot())
      return () => listeners.delete(listener)
    },
  }
}

/**
 * Reconcile a node port edit against existing edges.
 *
 * Renames are matched by direction and ordinal position, so connected edges
 * follow a deliberate rename. Removing or reordering a connected port is
 * rejected instead of leaving an edge that points at a missing handle.
 */
export function reconcileWorkflowNodePorts(
  definition: WorkflowDef,
  previousNode: WorkflowNode,
  nextNode: WorkflowNode,
): { ok: true; definition: WorkflowDef; renamedEdges: number } | { ok: false; reason: string; danglingEdges: WorkflowEdge[] } {
  const previousByDirection = portsByDirection(previousNode)
  const nextByDirection = portsByDirection(nextNode)
  const renameByDirection = new Map<string, Map<string, string>>()
  for (const direction of ['in', 'out'] as const) {
    const oldPorts = previousByDirection[direction]
    const newPorts = nextByDirection[direction]
    const map = new Map<string, string>()
    // A length change represents add/delete, not a rename. Without this
    // guard deleting the first port would look like renaming it to the old
    // second port and silently retarget a connection.
    if (oldPorts.length === newPorts.length) {
      for (let index = 0; index < oldPorts.length; index += 1) {
        const oldName = oldPorts[index].name
        const newName = newPorts[index].name
        if (oldName && newName && oldName !== newName) map.set(oldName, newName)
      }
    }
    renameByDirection.set(direction, map)
  }
  for (const direction of ['in', 'out'] as const) {
    const names = nextByDirection[direction].map((port) => port.name).filter(Boolean)
    if (new Set(names).size !== names.length) {
      return { ok: false, reason: `端口名称不能重复：${names.join(', ')}`, danglingEdges: [] }
    }
    const oldNames = previousByDirection[direction].map((port) => port.name)
    const sameNameSet = oldNames.length === names.length
      && oldNames.every((name) => names.includes(name))
    if (sameNameSet && oldNames.some((name, index) => name !== names[index])) {
      return {
        ok: false,
        reason: `${direction === 'in' ? '输入' : '输出'}端口顺序不能更改，否则会改变连线语义。`,
        danglingEdges: [],
      }
    }
  }
  const nextNames = new Set(nextNode.ports.map((port) => `${port.direction}:${port.name}`))
  const danglingEdges = definition.edges.filter((edge) => {
    if (edge.source === nextNode.id && !nextNames.has(`out:${renameByDirection.get('out')?.get(edge.source_port) || edge.source_port}`)) return true
    if (edge.target === nextNode.id && !nextNames.has(`in:${renameByDirection.get('in')?.get(edge.target_port) || edge.target_port}`)) return true
    return false
  })
  if (danglingEdges.length) {
    return {
      ok: false,
      reason: `无法删除仍被连线使用的端口：${danglingEdges.map((edge) => edge.source === nextNode.id ? edge.source_port : edge.target_port).join(', ')}`,
      danglingEdges,
    }
  }
  let renamedEdges = 0
  const edges = definition.edges.map((edge) => {
    const nextEdge = { ...edge }
    if (edge.source === nextNode.id) {
      const renamed = renameByDirection.get('out')?.get(edge.source_port)
      if (renamed) {
        nextEdge.source_port = renamed
        renamedEdges += 1
      }
    }
    if (edge.target === nextNode.id) {
      const renamed = renameByDirection.get('in')?.get(edge.target_port)
      if (renamed) {
        nextEdge.target_port = renamed
        renamedEdges += 1
      }
    }
    return nextEdge
  })
  return {
    ok: true,
    definition: {
      ...definition,
      nodes: definition.nodes.map((node) => node.id === nextNode.id ? cloneNode(nextNode) : node),
      edges,
    },
    renamedEdges,
  }
}

function cloneNode(node: WorkflowNode): WorkflowNode {
  return JSON.parse(JSON.stringify(node)) as WorkflowNode
}

function portsByDirection(node: WorkflowNode): { in: WorkflowNode['ports']; out: WorkflowNode['ports'] } {
  return {
    in: node.ports.filter((port) => port.direction === 'in'),
    out: node.ports.filter((port) => port.direction === 'out'),
  }
}

export function workflowNodeStateToStatus(state: WorkflowNodeState | undefined): string {
  return state?.status || 'idle'
}
