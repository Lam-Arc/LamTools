import type { WorkflowDef, WorkflowDocumentV2, WorkflowEdge, WorkflowNode, WorkflowPort } from './types'
import { normalizeCanvasElements } from './canvas'
import { workflowNodeKindForTypeId } from './catalog'
import {
  isWorkflowDocumentV2,
  workflowDefinitionToDocument,
  workflowDocumentToDefinition,
} from './document'

export interface WorkflowTemplate {
  id: string
  name: string
  description: string
  definition: Partial<WorkflowDef>
}

export type WorkflowExportFormat = 'native-v2' | 'comfyui-v1' | 'comfyui-v0.4'

export type WorkflowImportSource =
  | { kind: 'native-v2'; name: string; document: WorkflowDocumentV2 }
  | { kind: 'comfyui'; name: string; version: '0.4' | '1'; workflow: Record<string, unknown> }
  | { kind: 'legacy'; name: string; definition: WorkflowDef }

/** Small, editable starters. They are client-side templates, not hidden RPCs. */
export const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'blank',
    name: '空白工作流',
    description: '从一个空画布开始。',
    definition: { description: '', nodes: [], edges: [], input_params: [], output_port: '' },
  },
  {
    id: 'content-to-command',
    name: '内容 → 命令',
    description: '用常量节点注入文本，再交给命令节点。',
    definition: {
      nodes: [
        {
          id: 'constant-1', kind: 'constant', title: '常量', config: { value: '' },
          ports: [{ name: 'out', type: 'string', direction: 'out', value: '' }], position: { x: 80, y: 120 },
        },
        {
          id: 'command-1', kind: 'command', title: '命令', config: { command: '' },
          ports: [{ name: 'in', type: 'string', direction: 'in' }, { name: 'out', type: 'string', direction: 'out' }], position: { x: 360, y: 120 },
        },
      ],
      edges: [{ id: 'edge-1', source: 'constant-1', source_port: 'out', target: 'command-1', target_port: 'in' }],
      input_params: [], output_port: 'command-1.out',
    },
  },
  {
    id: 'prompt-json',
    name: '提示词 → JSON',
    description: '适合快速搭建结构化模型输出。',
    definition: {
      nodes: [
        {
          id: 'model-1', kind: 'model', type_id: 'model', title: '结构化模型', config: { instruction: '', model_id: '' },
          ports: [{ name: 'in', type: 'string', direction: 'in' }, { name: 'out', type: 'object', direction: 'out' }], position: { x: 180, y: 120 },
        },
      ],
      edges: [], input_params: [{ name: 'prompt', type: 'string', description: '输入提示词', required: true }], output_port: 'model-1.out',
    },
  },
]

/**
 * Normalize imported JSON at the UI boundary. This intentionally accepts the
 * old single-file and folder-merged shapes produced before stable ids/CAS.
 */
export function normalizeImportedWorkflow(value: unknown, fallbackName = '导入工作流'): WorkflowDef {
  const candidate = unwrapWorkflow(value)
  if (isWorkflowDocumentV2(candidate)) return workflowDocumentToDefinition(candidate)
  const raw = isRecord(candidate) ? candidate : {}
  const now = new Date().toISOString()
  const rawNodes = raw.nodes ?? raw.node_list ?? raw.steps
  const rawEdges = raw.edges ?? raw.connections ?? raw.links
  const nodes = normalizeNodes(rawNodes)
  const normalizedEdges = normalizeEdges(rawEdges)
  const edges = normalizedEdges.length ? normalizedEdges : normalizeMapEdges(raw.map)
  const inputParams = normalizeInputParams(raw.input_params ?? raw.inputParams ?? raw.inputs)
  const canvasRaw = raw.canvas_elements
    ?? raw.canvasElements
    ?? raw.graphical_elements
    ?? raw.graphicalElements
    ?? (isRecord(raw.canvas) ? raw.canvas.elements ?? raw.canvas : undefined)
  const canvasElements = normalizeCanvasElements(canvasRaw, raw)
  const name = String(raw.name ?? raw.workflow_name ?? raw.title ?? fallbackName).trim() || fallbackName
  return {
    id: String(raw.id ?? raw.workflow_id ?? '').trim(),
    name,
    description: String(raw.description ?? ''),
    nodes,
    edges,
    input_params: inputParams,
    output_port: String(raw.output_port ?? raw.outputPort ?? ''),
    exposed: Boolean(raw.exposed ?? false),
    tool_name: String(raw.tool_name ?? raw.toolName ?? ''),
    work_root: String(raw.work_root ?? raw.workRoot ?? ''),
    map: String(raw.map ?? ''),
    created_at: String(raw.created_at ?? raw.createdAt ?? now),
    updated_at: String(raw.updated_at ?? raw.updatedAt ?? now),
    ...(Array.isArray(raw.triggers) ? { triggers: cloneJson(raw.triggers) } : {}),
    ...(isRecord(raw.policies) ? { policies: cloneJson(raw.policies) } : {}),
    ...(canvasElements.length ? { canvas_elements: canvasElements } : {}),
    ...(raw.revision !== undefined ? { revision: normalizeRevision(raw.revision) } : {}),
  }
}

/** Classify imported JSON without projecting ComfyUI through the legacy map model. */
export function parseWorkflowImport(value: unknown, fallbackName = '导入工作流'): WorkflowImportSource {
  const candidate = unwrapWorkflow(value)
  if (isWorkflowDocumentV2(candidate)) {
    return {
      kind: 'native-v2',
      name: candidate.resource.name || fallbackName,
      document: cloneJson(candidate),
    }
  }
  if (isComfyUiWorkflow(candidate)) {
    const raw = cloneJson(candidate)
    const version = String(raw.version ?? '').startsWith('0.4') ? '0.4' : '1'
    return {
      kind: 'comfyui',
      name: String(raw.name ?? fallbackName).trim() || fallbackName,
      version,
      workflow: raw,
    }
  }
  const definition = normalizeImportedWorkflow(candidate, fallbackName)
  return { kind: 'legacy', name: definition.name, definition }
}

export function serializeWorkflowJson(definition: WorkflowDef): string {
  return JSON.stringify(workflowDefinitionToDocument(definition), null, 2)
}

/** Safely trigger a browser/Tauri download with an arbitrary JSON wire object. */
export function downloadJson(value: unknown, filename: string): boolean {
  if (typeof document === 'undefined' || typeof URL === 'undefined' || typeof Blob === 'undefined') return false
  const safeName = filename.trim() || 'workflow.json'
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = safeName.toLowerCase().endsWith('.json') ? safeName : `${safeName}.json`
  anchor.click()
  URL.revokeObjectURL(url)
  return true
}

/** Export the canonical Sunday V2 document, never the legacy projection/map. */
export function downloadWorkflowJson(definition: WorkflowDef, filename = ''): boolean {
  const safeName = filename.trim() || definition.name || 'workflow'
  return downloadJson(workflowDefinitionToDocument(definition), safeName)
}

function unwrapWorkflow(value: unknown): unknown {
  if (!isRecord(value)) return value
  if (isWorkflowDocumentV2(value.document)) return value.document
  if (isRecord(value.workflow)) return value.workflow
  if (isRecord(value.definition)) return value.definition
  return value
}

function isComfyUiWorkflow(value: unknown): value is Record<string, unknown> {
  if (!isRecord(value) || !Array.isArray(value.nodes)) return false
  const version = String(value.version ?? '')
  if (version !== '1' && !version.startsWith('0.4')) return false
  if ('last_node_id' in value || 'last_link_id' in value || 'reroutes' in value) return true
  return value.nodes.some((node) => isRecord(node)
    && (Array.isArray(node.pos) || Array.isArray(node.size) || Array.isArray(node.widgets_values))
    && ('type' in node || 'class_type' in node))
}

function normalizeNodes(value: unknown): WorkflowNode[] {
  const entries: Array<[string, unknown]> = Array.isArray(value)
    ? value.map((item, index) => [String(index), item])
    : isRecord(value) ? Object.entries(value) : []
  return entries.flatMap(([key, candidate], index) => {
    if (!isRecord(candidate)) return []
    const id = String(candidate.id ?? candidate.node_id ?? key ?? `node-${index}`).trim() || `node-${index}`
    const config = isRecord(candidate.config) ? { ...candidate.config } : {}
    // Old action files kept command/script fields beside the config object.
    if (candidate.command !== undefined && config.command === undefined) config.command = candidate.command
    if (candidate.script !== undefined && config.script === undefined) config.script = candidate.script
    if (candidate.instruction !== undefined && config.instruction === undefined) config.instruction = candidate.instruction
    const rawKind = String(candidate.kind ?? candidate.type ?? candidate.class_type ?? 'command').trim().toLowerCase()
    const kind = rawKind === 'action'
      ? (String(config.action_type ?? '').toLowerCase() === 'script' ? 'script' : 'command')
      : rawKind
    const typeId = String(candidate.type_id ?? candidate.class_type ?? (rawKind === 'action' ? kind : rawKind)).trim()
    const parentId = Object.prototype.hasOwnProperty.call(candidate, 'parent_id')
      ? candidate.parent_id
      : candidate.parentId
    return [{
      id,
      // Preserve registry/custom ids on import. Older action aliases still
      // resolve to their compatible editor kind above.
      kind: workflowNodeKindForTypeId(kind) as WorkflowNode['kind'],
      title: String(candidate.title ?? candidate.name ?? id),
      config,
      ports: normalizePorts(candidate.ports, candidate.inputs, candidate.outputs),
      position: normalizePosition(candidate.position ?? candidate),
      ...(parentId !== undefined && parentId !== null && String(parentId).trim()
        ? { parent_id: String(parentId).trim() }
        : {}),
      ...(typeId ? { type_id: typeId } : {}),
      ...(candidate.type_version !== undefined ? { type_version: Math.max(1, Number(candidate.type_version) || 1) } : {}),
    }]
  })
}

function normalizePorts(value: unknown, inputs?: unknown, outputs?: unknown): WorkflowPort[] {
  const source = Array.isArray(value) ? value : []
  if (source.length) return source.flatMap((item) => normalizePort(item))
  return [
    ...normalizePortMap(inputs, 'in'),
    ...normalizePortMap(outputs, 'out'),
  ]
}

function normalizePort(value: unknown, fallbackDirection: 'in' | 'out' = 'in'): WorkflowPort[] {
  if (!isRecord(value)) return []
  const direction: 'in' | 'out' = String(value.direction ?? fallbackDirection).toLowerCase() === 'out' ? 'out' : 'in'
  return [{
    ...(value.id !== undefined ? { id: String(value.id) } : {}),
    name: String(value.name ?? value.id ?? '').trim(),
    type: String(value.type ?? 'any'),
    direction,
    ...(value.description ? { description: String(value.description) } : {}),
    ...(value.required !== undefined ? { required: Boolean(value.required) } : {}),
    ...(value.lazy !== undefined ? { lazy: Boolean(value.lazy) } : {}),
    ...(value.value !== undefined ? { value: value.value } : {}),
  }].filter((port) => Boolean(port.name))
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function normalizePortMap(value: unknown, direction: 'in' | 'out'): WorkflowPort[] {
  if (Array.isArray(value)) return value.flatMap((item) => normalizePort(item, direction))
  if (!isRecord(value)) return []
  return Object.entries(value).flatMap(([name, candidate]) => {
    if (isRecord(candidate)) return normalizePort({ name, ...candidate }, direction)
    return [{ name, type: String(candidate || 'any'), direction }]
  })
}

function normalizeEdges(value: unknown): WorkflowEdge[] {
  const entries = Array.isArray(value) ? value : isRecord(value) ? Object.values(value) : []
  return entries.flatMap((candidate, index) => {
    if (!isRecord(candidate)) return []
    const source = String(candidate.source ?? candidate.from ?? candidate.source_node ?? '').trim()
    const target = String(candidate.target ?? candidate.to ?? candidate.target_node ?? '').trim()
    const sourcePort = String(candidate.source_port ?? candidate.sourcePort ?? candidate.from_port ?? '').trim()
    const targetPort = String(candidate.target_port ?? candidate.targetPort ?? candidate.to_port ?? '').trim()
    if (!source || !target || !sourcePort || !targetPort) return []
    return [{
      id: String(candidate.id ?? `edge-${index}`), source, source_port: sourcePort, target, target_port: targetPort,
      ...(candidate.source_port_id ?? candidate.sourcePortId ? { source_port_id: String(candidate.source_port_id ?? candidate.sourcePortId) } : {}),
      ...(candidate.target_port_id ?? candidate.targetPortId ? { target_port_id: String(candidate.target_port_id ?? candidate.targetPortId) } : {}),
      ...(hasExpression(candidate.transform)
        ? { transform: cloneJson(candidate.transform) }
        : {}),
      ...(hasExpression(candidate.condition)
        ? { condition: cloneJson(candidate.condition) }
        : {}),
    }]
  })
}

function normalizeMapEdges(value: unknown): WorkflowEdge[] {
  return String(value || '').split(/\r?\n/).flatMap((line, index) => {
    const match = line.trim().match(/^(\S+?)\.([^.>\s]+)(?:\.[^.>\s]+)?\s*->\s*(\S+?)\.([^.>\s]+)(?:\.[^.>\s]+)?$/)
    if (!match) return []
    const [, source, sourcePort, target, targetPort] = match
    return [{ id: `edge-map-${index}`, source, source_port: sourcePort, target, target_port: targetPort }]
  })
}

function hasExpression(value: unknown): boolean {
  return value !== undefined && value !== null && (typeof value !== 'string' || value.trim().length > 0)
}

function normalizeInputParams(value: unknown): WorkflowDef['input_params'] {
  if (Array.isArray(value)) {
    return value.flatMap((candidate) => normalizeInputParam(candidate))
  }
  if (isRecord(value)) {
    return Object.entries(value).flatMap(([name, candidate]) => normalizeInputParam(isRecord(candidate) ? { name, ...candidate } : { name, type: candidate }))
  }
  return []
}

function normalizeInputParam(value: unknown): WorkflowDef['input_params'] {
  if (!isRecord(value)) return []
  const name = String(value.name ?? value.id ?? '').trim()
  if (!name) return []
  return [{
    name,
    type: String(value.type ?? 'any'),
    ...(value.description ? { description: String(value.description) } : {}),
    required: Boolean(value.required ?? true),
    ...(value.default !== undefined ? { default: value.default } : {}),
  }]
}

function normalizePosition(value: unknown): { x: number; y: number } {
  const raw = isRecord(value) ? value : {}
  const x = Number(raw.x ?? 0)
  const y = Number(raw.y ?? 0)
  return { x: Number.isFinite(x) ? x : 0, y: Number.isFinite(y) ? y : 0 }
}

function normalizeRevision(value: unknown): number | string | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && /^\d+$/.test(value.trim())) return value.trim()
  return undefined
}

function isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
