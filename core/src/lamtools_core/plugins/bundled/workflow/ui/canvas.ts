import type { WorkflowDef, WorkflowEdge, WorkflowNode } from './types'
import { workflowNodeKindForTypeId } from './catalog'

/**
 * Canvas decorations are deliberately separate from executable workflow nodes.
 * The runtime only understands the latter, while the editor can still round
 * trip visual aids and old graph-editor exports without making them executable.
 */
export type WorkflowCanvasElementKind = 'group' | 'frame' | 'reroute' | 'note' | 'comment'

export interface WorkflowCanvasElement {
  id: string
  kind: WorkflowCanvasElementKind
  position: { x: number; y: number }
  width: number
  height: number
  title: string
  text: string
  color?: string
  parent_id?: string
  collapsed?: boolean
  z_index?: number
  /** Extension data from legacy editors is retained, but never executed. */
  data?: Record<string, unknown>
}

export interface WorkflowCanvasClipboardPayload {
  type: 'lamtools.workflow.clipboard'
  version: 1
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  canvas_elements: WorkflowCanvasElement[]
}

export const WORKFLOW_CANVAS_STORAGE_KEY = 'lamtools.workflow.canvas.v1'
export const WORKFLOW_CLIPBOARD_TYPE = 'lamtools.workflow.clipboard'
export const WORKFLOW_CLIPBOARD_VERSION = 1

const DEFAULT_ELEMENT_SIZE: Record<WorkflowCanvasElementKind, { width: number; height: number }> = {
  group: { width: 420, height: 260 },
  frame: { width: 420, height: 260 },
  reroute: { width: 28, height: 28 },
  note: { width: 240, height: 130 },
  comment: { width: 280, height: 110 },
}

const DEFAULT_ELEMENT_Z_INDEX: Record<WorkflowCanvasElementKind, number> = {
  frame: 0,
  group: 1,
  note: 4,
  comment: 5,
  reroute: 30,
}

/** Stable visual stacking bands; executable edges/nodes occupy 10/20. */
export function workflowCanvasElementZIndex(kind: WorkflowCanvasElementKind): number {
  return DEFAULT_ELEMENT_Z_INDEX[kind]
}

export interface WorkflowCanvasElementContents {
  /** Executable nodes explicitly linked or geometrically contained by the selected container. */
  nodeIds: string[]
  /** Canvas elements inside the selected container, including nested descendants. */
  canvasElementIds: string[]
}

export interface WorkflowCanvasElementDeletion {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  canvas_elements: WorkflowCanvasElement[]
  deletedNodeIds: string[]
  deletedCanvasElementIds: string[]
}

type WorkflowCanvasDefinition = Pick<WorkflowDef, 'nodes' | 'edges'> & {
  canvas_elements?: WorkflowCanvasElement[]
}

/** Frames and groups are the only canvas elements that own other content. */
export function isWorkflowCanvasContainer(element: WorkflowCanvasElement | undefined): element is WorkflowCanvasElement {
  return element?.kind === 'frame' || element?.kind === 'group'
}

/**
 * Resolve the contents of a frame/group for selection and destructive actions.
 *
 * Explicit ``parent_id`` links are authoritative for both nodes and canvas
 * elements. Legacy items without a parent field fall back to full rectangle
 * containment so an overlapping item is not selected accidentally. The
 * returned order follows the source definition order.
 */
export function workflowCanvasElementContents(
  definition: Pick<WorkflowDef, 'nodes'> & { canvas_elements?: WorkflowCanvasElement[] },
  containerId: string,
): WorkflowCanvasElementContents {
  const elements = definition.canvas_elements ?? []
  const container = elements.find((element) => element.id === containerId)
  if (!isWorkflowCanvasContainer(container)) return { nodeIds: [], canvasElementIds: [] }

  const childrenByParent = new Map<string, string[]>()
  for (const item of [...elements, ...definition.nodes]) {
    if (!item.parent_id) continue
    const children = childrenByParent.get(item.parent_id) ?? []
    children.push(item.id)
    childrenByParent.set(item.parent_id, children)
  }

  // Walk all explicit descendants, not just direct children. When a legacy
  // nested container is discovered by geometry, walk its explicit children
  // too; otherwise deleting the outer container would leave those children
  // orphaned. The visited set also keeps malformed cyclic metadata from
  // looping forever.
  const elementsById = new Map(elements.map((element) => [element.id, element]))
  const resolvedDescendants = new Set<string>()
  const pending = [container.id]
  while (pending.length) {
    const parentId = pending.shift() as string
    for (const childId of childrenByParent.get(parentId) ?? []) {
      if (childId === container.id || resolvedDescendants.has(childId)) continue
      resolvedDescendants.add(childId)
      pending.push(childId)
    }

    const parent = elementsById.get(parentId)
    if (!isWorkflowCanvasContainer(parent)) continue
    const parentBounds = canvasElementBounds(parent)
    for (const candidate of elements) {
      if (candidate.id === container.id || candidate.parent_id || !isWorkflowCanvasContainer(candidate)) continue
      if (!rectangleContains(parentBounds, canvasElementBounds(candidate))) continue
      if (resolvedDescendants.has(candidate.id)) continue
      resolvedDescendants.add(candidate.id)
      pending.push(candidate.id)
    }
  }

  const containerBounds = canvasElementBounds(container)
  const canvasElementIds = elements
    .filter((element) => element.id !== container.id)
    .filter((element) => resolvedDescendants.has(element.id)
      || (!element.parent_id && rectangleContains(containerBounds, canvasElementBounds(element))))
    .map((element) => element.id)
  const nodeIds = definition.nodes
    .filter((node) => resolvedDescendants.has(node.id)
      || (!node.parent_id && rectangleContains(containerBounds, workflowNodeBounds(node))))
    .map((node) => node.id)

  return { nodeIds, canvasElementIds }
}

/**
 * Remove a container, all resolved contents, and edges attached to removed
 * nodes. The input is never mutated; callers can emit the returned arrays as
 * the next workflow definition.
 */
export function deleteWorkflowCanvasElementContents(
  definition: WorkflowCanvasDefinition,
  containerId: string,
): WorkflowCanvasElementDeletion {
  const elements = definition.canvas_elements ?? []
  if (!isWorkflowCanvasContainer(elements.find((element) => element.id === containerId))) {
    return {
      nodes: [...definition.nodes],
      edges: [...definition.edges],
      canvas_elements: [...elements],
      deletedNodeIds: [],
      deletedCanvasElementIds: [],
    }
  }
  const contents = workflowCanvasElementContents(definition, containerId)
  const deletedNodeIds = contents.nodeIds
  const deletedCanvasElementIds = [containerId, ...contents.canvasElementIds]
  const deletedNodes = new Set(deletedNodeIds)
  const deletedElements = new Set(deletedCanvasElementIds)

  return {
    nodes: definition.nodes.filter((node) => !deletedNodes.has(node.id)),
    edges: definition.edges.filter((edge) => !deletedNodes.has(edge.source) && !deletedNodes.has(edge.target)),
    canvas_elements: elements.filter((element) => !deletedElements.has(element.id)),
    deletedNodeIds,
    deletedCanvasElementIds: elements
      .filter((element) => deletedElements.has(element.id))
      .map((element) => element.id),
  }
}

const KIND_ALIASES: Record<string, WorkflowCanvasElementKind> = {
  group: 'group',
  groups: 'group',
  container: 'group',
  box: 'group',
  frame: 'frame',
  frames: 'frame',
  section: 'frame',
  reroute: 'reroute',
  reroutes: 'reroute',
  redirect: 'reroute',
  waypoint: 'reroute',
  junction: 'reroute',
  note: 'note',
  notes: 'note',
  sticky: 'note',
  comment: 'comment',
  comments: 'comment',
  annotation: 'comment',
}

let memoryClipboardText = ''

export function hasWorkflowClipboardPayload(): boolean {
  return Boolean(parseWorkflowClipboardPayload(memoryClipboardText))
}

/** Normalize a visual element from current and pre-stable graph-editor JSON. */
export function normalizeCanvasElement(value: unknown, key = ''): WorkflowCanvasElement | null {
  if (!isRecord(value)) return null
  const rawKind = String(value.kind ?? value.type ?? value.element_type ?? value.elementType ?? key ?? '').trim().toLowerCase()
  const kind = KIND_ALIASES[rawKind]
  if (!kind) return null
  const id = String(value.id ?? value.element_id ?? value.elementId ?? key ?? `${kind}-1`).trim()
  if (!id) return null
  const size = DEFAULT_ELEMENT_SIZE[kind]
  const bounding = Array.isArray(value.bounding) ? value.bounding : []
  const rawSize = Array.isArray(value.size) ? value.size : []
  const position = normalizePosition(value.position ?? value.pos ?? value.bounding ?? value)
  const width = finiteNumber(value.width ?? value.w ?? rawSize[0] ?? bounding[2], size.width)
  const height = finiteNumber(value.height ?? value.h ?? rawSize[1] ?? bounding[3], size.height)
  const text = String(value.text ?? value.content ?? value.body ?? value.comment ?? value.note ?? '')
  const title = String(value.title ?? value.name ?? (kind === 'reroute' ? '中继' : kind === 'comment' ? '注释' : kind === 'note' ? '便签' : kind === 'frame' ? '框架' : '分组'))
  const parent = value.parent_id ?? value.parentId ?? value.parent ?? value.group_id ?? value.groupId
  const known = new Set([
    'id', 'element_id', 'elementId', 'kind', 'type', 'element_type', 'elementType',
    'position', 'x', 'y', 'size', 'width', 'height', 'w', 'h', 'title', 'name',
    'text', 'content', 'body', 'comment', 'note', 'parent_id', 'parentId', 'parent',
    'group_id', 'groupId', 'color', 'collapsed', 'z_index', 'zIndex', 'data',
  ])
  const extension = isRecord(value.data) ? { ...value.data } : {}
  for (const [name, item] of Object.entries(value)) {
    if (!known.has(name)) extension[name] = item
  }
  return {
    id,
    kind,
    position,
    width: Math.max(20, width),
    height: Math.max(20, height),
    title,
    text,
    ...(value.color !== undefined ? { color: String(value.color) } : {}),
    ...(parent ? { parent_id: String(parent) } : {}),
    ...(value.collapsed !== undefined ? { collapsed: Boolean(value.collapsed) } : {}),
    ...(value.z_index !== undefined || value.zIndex !== undefined
      ? { z_index: Number(value.z_index ?? value.zIndex) || 0 }
      : {}),
    ...(Object.keys(extension).length ? { data: extension } : {}),
  }
}

/** Normalize arrays, maps, wrappers, and the common legacy per-kind buckets. */
export function normalizeCanvasElements(value: unknown, legacyBuckets?: Record<string, unknown>): WorkflowCanvasElement[] {
  const entries: Array<[string, unknown]> = []
  const append = (key: string, item: unknown, kindHint = ''): void => {
    if (KIND_ALIASES[key]) {
      if (Array.isArray(item)) {
        item.forEach((child, index) => append(`${key}-${index}`, child, key))
        return
      }
      if (isRecord(item) && !('id' in item) && !('kind' in item) && !('type' in item)) {
        Object.entries(item).forEach(([childKey, child]) => append(childKey, child, key))
        return
      }
    }
    if (kindHint && isRecord(item) && !item.kind && !item.type) entries.push([key, { ...item, kind: kindHint }])
    else entries.push([key, item])
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => append(String(index), item))
  } else if (isRecord(value)) {
    if (value.kind || value.type || value.element_type || value.elementType) {
      append('0', value)
    } else if (Array.isArray(value.elements)) {
      value.elements.forEach((item, index) => append(String(index), item))
    } else {
      Object.entries(value).forEach(([key, item]) => append(key, item))
    }
  }
  if (legacyBuckets) {
    for (const bucket of ['groups', 'frames', 'reroutes', 'notes', 'comments']) {
      const items = legacyBuckets[bucket]
      append(bucket, items)
    }
  }
  const seen = new Set<string>()
  return entries.flatMap(([key, item]) => {
    const normalized = normalizeCanvasElement(item, key)
    if (!normalized || seen.has(normalized.id)) return []
    seen.add(normalized.id)
    return [normalized]
  })
}

/** Return only executable nodes and decorations that are actually selected. */
export function createWorkflowClipboardPayload(
  definition: Pick<WorkflowDef, 'nodes' | 'edges'> & { canvas_elements?: WorkflowCanvasElement[] },
  selectedIds: Iterable<string>,
): WorkflowCanvasClipboardPayload {
  const ids = new Set(selectedIds)
  const nodes = definition.nodes.filter((node) => ids.has(node.id)).map(clone)
  const canvasElements = (definition.canvas_elements ?? []).filter((element) => ids.has(element.id)).map(clone)
  const nodeIds = new Set(nodes.map((node) => node.id))
  const edges = definition.edges
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map(clone)
  return {
    type: WORKFLOW_CLIPBOARD_TYPE,
    version: WORKFLOW_CLIPBOARD_VERSION,
    nodes,
    edges,
    canvas_elements: canvasElements,
  }
}

/** Parse the versioned clipboard contract, accepting old plain node/edge JSON. */
export function parseWorkflowClipboardPayload(value: unknown): WorkflowCanvasClipboardPayload | null {
  let candidate: unknown = value
  if (typeof value === 'string') {
    try { candidate = JSON.parse(value) } catch { return null }
  }
  if (!isRecord(candidate)) return null
  const rawNodes = Array.isArray(candidate.nodes) ? candidate.nodes : []
  const nodes = rawNodes.flatMap((item) => normalizeClipboardNode(item))
  const nodeIds = new Set(nodes.map((node) => node.id))
  const rawEdges = Array.isArray(candidate.edges) ? candidate.edges : []
  const edges = rawEdges.flatMap((item) => normalizeClipboardEdge(item)).filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
  const rawElements = candidate.canvas_elements ?? candidate.canvasElements ?? candidate.elements ?? []
  const canvasElements = normalizeCanvasElements(rawElements)
  if (!nodes.length && !canvasElements.length) return null
  return {
    type: WORKFLOW_CLIPBOARD_TYPE,
    version: WORKFLOW_CLIPBOARD_VERSION,
    nodes,
    edges,
    canvas_elements: canvasElements,
  }
}

export interface WorkflowClipboardPasteResult {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  canvas_elements: WorkflowCanvasElement[]
}

/** Remap ids and endpoints so a paste can safely cross workflows. */
export function remapWorkflowClipboard(
  payload: WorkflowCanvasClipboardPayload,
  existingIds: Iterable<string> = [],
  anchor?: { x: number; y: number },
): WorkflowClipboardPasteResult {
  const used = new Set(existingIds)
  const idMap = new Map<string, string>()
  const nextId = (oldId: string, prefix: string): string => {
    const base = oldId.replace(/[^a-zA-Z0-9_-]/g, '-') || prefix
    let next = `${base}-copy`
    let suffix = 2
    while (used.has(next)) next = `${base}-copy-${suffix++}`
    used.add(next)
    idMap.set(oldId, next)
    return next
  }
  const allPositions = [
    ...payload.nodes.map((node) => node.position),
    ...payload.canvas_elements.map((element) => element.position),
  ]
  const minX = allPositions.length ? Math.min(...allPositions.map((position) => position.x)) : 0
  const minY = allPositions.length ? Math.min(...allPositions.map((position) => position.y)) : 0
  const offset = anchor ? { x: anchor.x - minX, y: anchor.y - minY } : { x: 24, y: 24 }
  // Reserve every node/element id before cloning so parent links can be
  // remapped regardless of whether the parent appears later in the payload.
  for (const node of payload.nodes) nextId(node.id, node.kind)
  for (const element of payload.canvas_elements) nextId(element.id, element.kind)

  const nodes = payload.nodes.map((node) => {
    const { parent_id: _parentId, ...clonedNode } = clone(node)
    return {
      ...clonedNode,
      id: idMap.get(node.id) || node.id,
      position: { x: node.position.x + offset.x, y: node.position.y + offset.y },
      ...(node.parent_id && idMap.has(node.parent_id) ? { parent_id: idMap.get(node.parent_id) } : {}),
    }
  })
  const canvas_elements = payload.canvas_elements.map((element) => {
    const { parent_id: _parentId, ...clonedElement } = clone(element)
    return {
      ...clonedElement,
      id: idMap.get(element.id) || element.id,
      position: { x: element.position.x + offset.x, y: element.position.y + offset.y },
      ...(element.parent_id && idMap.has(element.parent_id) ? { parent_id: idMap.get(element.parent_id) } : {}),
    }
  })
  const edges = payload.edges.flatMap((edge, index) => {
    const source = idMap.get(edge.source)
    const target = idMap.get(edge.target)
    if (!source || !target) return []
    const id = nextId(edge.id || `edge-${index}`, 'edge')
    return [{ ...clone(edge), id, source, target }]
  })
  return { nodes, edges, canvas_elements }
}

/** Browser clipboard write with a memory fallback for Tauri/webview/test hosts. */
export async function writeWorkflowClipboardPayload(payload: WorkflowCanvasClipboardPayload): Promise<boolean> {
  const text = JSON.stringify(payload)
  memoryClipboardText = text
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // Continue to the textarea fallback; clipboard permissions are optional.
  }
  if (typeof document !== 'undefined') {
    try {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', 'true')
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      const copied = document.execCommand?.('copy') === true
      textarea.remove()
      return copied || true
    } catch {
      // The in-memory value remains usable in constrained hosts.
    }
  }
  return false
}

/** Browser clipboard read with the same memory fallback used by writes. */
export async function readWorkflowClipboardPayload(): Promise<WorkflowCanvasClipboardPayload | null> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.readText) {
      const parsed = parseWorkflowClipboardPayload(await navigator.clipboard.readText())
      if (parsed) return parsed
    }
  } catch {
    // Permission denied or an unsupported webview: use the local fallback.
  }
  return parseWorkflowClipboardPayload(memoryClipboardText)
}

/** Keep editor-only canvas metadata across backend round-trips. */
export function readWorkflowCanvasSidecar(workflowId: string): WorkflowCanvasElement[] {
  if (!workflowId || typeof localStorage === 'undefined') return []
  try {
    const raw = JSON.parse(localStorage.getItem(WORKFLOW_CANVAS_STORAGE_KEY) || '{}')
    return normalizeCanvasElements(isRecord(raw) ? raw[workflowId] : [])
  } catch { return [] }
}

export function writeWorkflowCanvasSidecar(workflowId: string, elements: WorkflowCanvasElement[]): void {
  if (!workflowId || typeof localStorage === 'undefined') return
  try {
    const raw = JSON.parse(localStorage.getItem(WORKFLOW_CANVAS_STORAGE_KEY) || '{}')
    const store = isRecord(raw) ? raw : {}
    store[workflowId] = elements.map(clone)
    localStorage.setItem(WORKFLOW_CANVAS_STORAGE_KEY, JSON.stringify(store))
  } catch {
    // Local storage is an enhancement; document editing must still work.
  }
}

export function mergeWorkflowCanvasSidecar(definition: WorkflowDef): WorkflowDef {
  const current = definition.canvas_elements ?? []
  if (current.length || !definition.id) return definition
  const sidecar = readWorkflowCanvasSidecar(definition.id)
  return sidecar.length ? { ...definition, canvas_elements: sidecar } : definition
}

export type WorkflowNodeAlignment = 'left' | 'center' | 'right' | 'top' | 'middle' | 'bottom'
export type WorkflowNodeDistribution = 'horizontal' | 'vertical'

/** Pure geometry helpers make alignment deterministic and easy to test. */
export function alignWorkflowNodes(nodes: WorkflowNode[], alignment: WorkflowNodeAlignment): WorkflowNode[] {
  if (nodes.length < 2) return nodes.map(clone)
  const dimensions = nodes.map((node) => ({ node, width: nodeSize(node).width, height: nodeSize(node).height }))
  const left = Math.min(...dimensions.map(({ node }) => node.position.x))
  const top = Math.min(...dimensions.map(({ node }) => node.position.y))
  const right = Math.max(...dimensions.map(({ node, width }) => node.position.x + width))
  const bottom = Math.max(...dimensions.map(({ node, height }) => node.position.y + height))
  const centerX = (left + right) / 2
  const centerY = (top + bottom) / 2
  return dimensions.map(({ node, width, height }) => {
    const position = { ...node.position }
    if (alignment === 'left') position.x = left
    if (alignment === 'center') position.x = centerX - width / 2
    if (alignment === 'right') position.x = right - width
    if (alignment === 'top') position.y = top
    if (alignment === 'middle') position.y = centerY - height / 2
    if (alignment === 'bottom') position.y = bottom - height
    return { ...clone(node), position }
  })
}

export function distributeWorkflowNodes(nodes: WorkflowNode[], direction: WorkflowNodeDistribution): WorkflowNode[] {
  if (nodes.length < 3) return nodes.map(clone)
  const result = nodes.map(clone)
  const ordered = result.slice().sort((a, b) => direction === 'horizontal' ? a.position.x - b.position.x : a.position.y - b.position.y)
  const first = ordered[0]
  const last = ordered[ordered.length - 1]
  const firstStart = direction === 'horizontal' ? first.position.x : first.position.y
  const lastStart = direction === 'horizontal' ? last.position.x : last.position.y
  const lastSize = direction === 'horizontal' ? nodeSize(last).width : nodeSize(last).height
  const totalSize = ordered.reduce((sum, node) => sum + (direction === 'horizontal' ? nodeSize(node).width : nodeSize(node).height), 0)
  const gap = (lastStart + lastSize - firstStart - totalSize) / (ordered.length - 1)
  let cursor = firstStart
  for (const node of ordered) {
    if (direction === 'horizontal') node.position.x = cursor
    else node.position.y = cursor
    cursor += (direction === 'horizontal' ? nodeSize(node).width : nodeSize(node).height) + gap
  }
  const byId = new Map(ordered.map((node) => [node.id, node]))
  return result.map((node) => byId.get(node.id) || node)
}

function normalizeClipboardNode(value: unknown): WorkflowNode[] {
  if (!isRecord(value)) return []
  const id = String(value.id ?? value.node_id ?? '').trim()
  const kind = String(value.kind ?? value.type ?? value.class_type ?? 'command').trim().toLowerCase()
  if (!id || !kind) return []
  const parentId = value.parent_id ?? value.parentId
  const rawPorts = Array.isArray(value.ports) ? value.ports : []
  const ports = rawPorts.flatMap((port) => {
    if (!isRecord(port)) return []
    const name = String(port.name ?? port.id ?? '').trim()
    if (!name) return []
    return [{
      name,
      type: String(port.type ?? 'any'),
      direction: String(port.direction ?? 'in').toLowerCase() === 'out' ? 'out' as const : 'in' as const,
      ...(port.description ? { description: String(port.description) } : {}),
      ...(port.value !== undefined ? { value: port.value } : {}),
    }]
  })
  return [{
    id,
    kind: workflowNodeKindForTypeId(kind) as WorkflowNode['kind'],
    title: String(value.title ?? value.name ?? id),
    config: isRecord(value.config) ? { ...value.config } : {},
    ports,
    position: normalizePosition(value.position ?? value),
    ...(parentId ? { parent_id: String(parentId) } : {}),
    ...(value.type_id !== undefined || value.class_type !== undefined ? { type_id: String(value.type_id ?? value.class_type) } : {}),
    ...(value.type_version !== undefined ? { type_version: Math.max(1, Number(value.type_version) || 1) } : {}),
  }]
}

function normalizeClipboardEdge(value: unknown): WorkflowEdge[] {
  if (!isRecord(value)) return []
  const source = String(value.source ?? value.from ?? '').trim()
  const target = String(value.target ?? value.to ?? '').trim()
  const sourcePort = String(value.source_port ?? value.sourcePort ?? value.from_port ?? '').trim()
  const targetPort = String(value.target_port ?? value.targetPort ?? value.to_port ?? '').trim()
  if (!source || !target || !sourcePort || !targetPort) return []
  return [{
    id: String(value.id ?? `edge-${source}-${target}`),
    source,
    source_port: sourcePort,
    target,
    target_port: targetPort,
    ...(value.transform ? { transform: String(value.transform) } : {}),
    ...(value.condition ? { condition: String(value.condition) } : {}),
  }]
}

function normalizePosition(value: unknown): { x: number; y: number } {
  if (Array.isArray(value)) return { x: finiteNumber(value[0], 0), y: finiteNumber(value[1], 0) }
  const raw = isRecord(value) ? value : {}
  return { x: finiteNumber(raw.x, 0), y: finiteNumber(raw.y, 0) }
}

function finiteNumber(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

interface WorkflowCanvasRect {
  x: number
  y: number
  width: number
  height: number
}

function canvasElementBounds(element: WorkflowCanvasElement): WorkflowCanvasRect {
  const position = element.position || { x: 0, y: 0 }
  const x = finiteNumber(position.x, 0)
  const y = finiteNumber(position.y, 0)
  // parent_id is intentionally data-only in the current canvas: positions
  // stay in the existing absolute coordinate space until a full reparenting
  // coordinate transform is introduced.
  const fallbackSize = DEFAULT_ELEMENT_SIZE[element.kind]
  return {
    x,
    y,
    width: Math.max(0, finiteNumber(element.width, fallbackSize.width)),
    height: Math.max(0, finiteNumber(element.height, fallbackSize.height)),
  }
}

function workflowNodeBounds(node: WorkflowNode): WorkflowCanvasRect {
  const raw = node as unknown as Record<string, unknown>
  const dimensions = isRecord(raw.dimensions) ? raw.dimensions : {}
  return {
    x: finiteNumber(node.position?.x, 0),
    y: finiteNumber(node.position?.y, 0),
    width: Math.max(0, finiteNumber(raw.width ?? dimensions.width, 180)),
    height: Math.max(0, finiteNumber(raw.height ?? dimensions.height, 100)),
  }
}

function rectangleContains(outer: WorkflowCanvasRect, inner: WorkflowCanvasRect): boolean {
  const outerRight = outer.x + outer.width
  const outerBottom = outer.y + outer.height
  const innerRight = inner.x + inner.width
  const innerBottom = inner.y + inner.height
  return inner.x >= outer.x
    && inner.y >= outer.y
    && innerRight <= outerRight
    && innerBottom <= outerBottom
}

function nodeSize(node: WorkflowNode): { width: number; height: number } {
  const dimensions = isRecord((node as unknown as Record<string, unknown>).dimensions)
    ? (node as unknown as Record<string, unknown>).dimensions as Record<string, unknown>
    : {}
  return { width: finiteNumber(dimensions.width, 180), height: finiteNumber(dimensions.height, 100) }
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
