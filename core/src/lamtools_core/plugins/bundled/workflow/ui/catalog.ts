import type {
  WorkflowNode,
  WorkflowNodeKind,
  WorkflowNodeSchema,
  WorkflowPort,
  WorkflowSchemaField,
} from './types'
import {
  WORKFLOW_LEGACY_NODE_KINDS,
} from './types'

/** Storage key is versioned so a future preference shape can migrate cleanly. */
export const WORKFLOW_CATALOG_STORAGE_KEY = 'lamtools.workflow.node-catalog.v1'

export interface WorkflowCatalogPreferences {
  recent: string[]
  favorites: string[]
}

export type WorkflowCatalogVariant = 'sidebar' | 'popover'

export interface NormalizedSchemaField extends WorkflowSchemaField {
  name: string
  required: boolean
  type: string
  enum?: unknown[]
}

const DEFAULT_PREFERENCES: WorkflowCatalogPreferences = { recent: [], favorites: [] }
const MAX_RECENT = 12

/** Canonical ids are useful to consumers that need to build a stable menu. */
export const WORKFLOW_CANONICAL_NODE_KINDS = [
  'model', 'agent', 'command', 'python', 'constant', 'input', 'output',
  'template', 'condition', 'merge', 'join', 'wait_event', 'approval', 'subgraph',
] as const

/** Registry entries that are compatibility aliases, not new-node choices. */
export const WORKFLOW_HIDDEN_NODE_KINDS = [...WORKFLOW_LEGACY_NODE_KINDS] as string[]

/**
 * Localized labels are presentation-only.  Registry ids, schema keys, and
 * stored preference values continue to use their canonical (usually English)
 * ids so that adding a node never changes the execution contract.
 */
export const WORKFLOW_NODE_LABELS: Readonly<Record<string, string>> = {
  model: '模型',
  agent: '智能体',
  approval: '人工审批',
  command: '命令',
  python: 'Python 脚本',
  constant: '常量',
  input: '输入',
  output: '输出',
  template: '模板',
  condition: '条件',
  merge: '合并',
  join: '汇聚',
  subgraph: '子工作流',
  wait_event: '等待事件',
  ai: 'AI（兼容）',
  script: 'Python 脚本（兼容）',
  content: '内容（兼容）',
  transform: '转换（兼容）',
  branch: '分支（兼容）',
}

/** Short descriptions keep catalog rows useful without exposing raw schema copy. */
export const WORKFLOW_NODE_DESCRIPTIONS: Readonly<Record<string, string>> = {
  model: '使用选定模型生成结果。',
  agent: '调用智能体执行任务，可按需使用工具。',
  approval: '暂停工作流，等待人工批准或拒绝。',
  command: '运行一条 Shell 命令。',
  python: '执行 Python 脚本，并通过端口传递变量。',
  constant: '输出预设的常量值。',
  input: '接收工作流输入。',
  output: '输出工作流结果。',
  template: '按照模板生成文本。',
  condition: '按条件选择后续分支。',
  merge: '合并多个输入，取首个有效值。',
  join: '汇聚具名输入并收集为对象。',
  subgraph: '调用另一个工作流。',
  wait_event: '等待外部事件后继续执行。',
  ai: '兼容旧版 AI 节点。',
  script: '兼容旧版 Python 脚本节点。',
  content: '兼容旧版内容节点。',
  transform: '兼容旧版转换节点。',
  branch: '兼容旧版分支节点。',
}

const WORKFLOW_CATEGORY_LABELS: Readonly<Record<string, string>> = {
  workflow: '工作流',
  'workflow/model': '模型',
  'workflow/agent': '智能体',
  'workflow/runtime': '运行时',
  'workflow/data': '数据',
  'workflow/composition': '编排',
  'workflow/control': '控制',
  'workflow/input': '输入',
  'workflow/output': '输出',
  'workflow/io': '输入输出',
  'workflow/transform': '转换',
  'workflow/human': '人工协作',
  'workflow/legacy': '兼容',
}

const WORKFLOW_CATEGORY_SEGMENT_LABELS: Readonly<Record<string, string>> = {
  ai: '智能',
  agent: '智能体',
  command: '命令',
  composition: '编排',
  control: '控制',
  data: '数据',
  input: '输入',
  human: '人工协作',
  io: '输入输出',
  legacy: '兼容',
  model: '模型',
  output: '输出',
  runtime: '运行时',
  test: '测试',
  transform: '转换',
  vendor: '扩展',
  workflow: '工作流',
}

export function workflowNodeTypeId(schema: WorkflowNodeSchema | null | undefined, fallback = ''): string {
  return String(schema?.type_id ?? schema?.name ?? fallback).trim()
}

/** Resolve the visible node name while retaining the registry's canonical id. */
export function workflowNodeDisplayName(
  schema: WorkflowNodeSchema | null | undefined,
  fallback = '未命名节点',
): string {
  const typeId = workflowNodeTypeId(schema).toLowerCase()
  const localized = (schema as Record<string, unknown> | null | undefined)?.display_name_zh
    ?? (schema as Record<string, unknown> | null | undefined)?.title_zh
  if (typeof localized === 'string' && localized.trim()) return localized.trim()
  return WORKFLOW_NODE_LABELS[typeId]
    || String(schema?.display_name ?? schema?.title ?? schema?.name ?? fallback).trim()
    || fallback
}

/** Resolve the visible catalog/category label without changing filter values. */
export function workflowCategoryDisplayName(category: unknown): string {
  const canonical = String(category || 'workflow').trim() || 'workflow'
  if (canonical === '全部') return canonical
  if (WORKFLOW_CATEGORY_LABELS[canonical]) return WORKFLOW_CATEGORY_LABELS[canonical]
  const segments = canonical.replace(/^workflow\//i, '').split(/[\\/._:-]+/).filter(Boolean)
  if (!segments.length) return '工作流'
  return segments.map((segment) => WORKFLOW_CATEGORY_SEGMENT_LABELS[segment.toLowerCase()] || '自定义').join(' / ')
}

/** Resolve a localized description, with the raw description retained for search. */
export function workflowSchemaDescription(schema: WorkflowNodeSchema | null | undefined): string {
  const typeId = workflowNodeTypeId(schema).toLowerCase()
  const localized = (schema as Record<string, unknown> | null | undefined)?.description_zh
  if (typeof localized === 'string' && localized.trim()) return localized.trim()
  return WORKFLOW_NODE_DESCRIPTIONS[typeId]
    || String(schema?.description || '').trim()
    || '自定义工作流节点。'
}

/** Search aliases include both localized copy and the original registry data. */
export function workflowSchemaSearchValues(
  schema: WorkflowNodeSchema,
  fallbackKey = '',
): string[] {
  return [
    workflowNodeTypeId(schema, fallbackKey),
    schema.name,
    schema.type_id,
    schema.display_name,
    schema.title,
    schema.description,
    schema.category,
    workflowNodeDisplayName(schema),
    workflowSchemaDescription(schema),
    ...(Array.isArray(schema.tags) ? schema.tags : []),
    ...(Array.isArray(schema.keywords) ? schema.keywords : []),
  ].map((value) => String(value || '').trim()).filter(Boolean)
}

/** Resolve a schema's editor kind without collapsing custom ids into command. */
export function workflowNodeKindForTypeId(typeId: unknown, fallback: WorkflowNodeKind = 'command'): WorkflowNodeKind {
  const value = String(typeId || '').trim()
  return value || fallback
}

/**
 * Registry visibility is data-driven.  `ai` is the one legacy id that older
 * hosts do not annotate, so it is treated as hidden unless explicitly marked
 * visible/modern.  Existing documents bypass this helper and stay renderable.
 */
export function isWorkflowSchemaHidden(schema: WorkflowNodeSchema | null | undefined): boolean {
  if (!schema) return true
  const raw = schema as Record<string, unknown>
  if (raw.hidden === true || raw.visible === false || raw.deprecated === true || raw.legacy === true) return true
  const id = workflowNodeTypeId(schema).toLowerCase()
  if (id === 'ai' && raw.visible !== true && raw.legacy !== false && raw.deprecated !== false) return true
  return false
}

/** Include hidden entries only for explicit compatibility/debug consumers. */
export function workflowCatalogEntries(
  schemas: Record<string, WorkflowNodeSchema> | null | undefined,
  options: { includeHidden?: boolean } = {},
): Array<{ key: string; schema: WorkflowNodeSchema }> {
  return Object.entries(schemas || {})
    .map(([key, schema]) => ({ key, schema }))
    .filter(({ schema }) => schema && typeof schema === 'object')
    .filter(({ schema }) => options.includeHidden === true || !isWorkflowSchemaHidden(schema))
}

/** Safely read catalog preferences in a browser, webview, or SSR/test host. */
export function readWorkflowCatalogPreferences(
  storage: Pick<Storage, 'getItem'> | null | undefined = typeof localStorage === 'undefined' ? undefined : localStorage,
): WorkflowCatalogPreferences {
  if (!storage) return { ...DEFAULT_PREFERENCES }
  try {
    const raw = storage.getItem(WORKFLOW_CATALOG_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_PREFERENCES }
    const parsed = JSON.parse(raw) as Record<string, unknown>
    return {
      recent: normalizeStringList(parsed.recent).slice(0, MAX_RECENT),
      favorites: normalizeStringList(parsed.favorites),
    }
  } catch {
    return { ...DEFAULT_PREFERENCES }
  }
}

export function writeWorkflowCatalogPreferences(
  preferences: WorkflowCatalogPreferences,
  storage: Pick<Storage, 'setItem'> | null | undefined = typeof localStorage === 'undefined' ? undefined : localStorage,
): void {
  if (!storage) return
  try {
    storage.setItem(WORKFLOW_CATALOG_STORAGE_KEY, JSON.stringify({
      recent: normalizeStringList(preferences.recent).slice(0, MAX_RECENT),
      favorites: normalizeStringList(preferences.favorites),
    }))
  } catch {
    // A private browsing/webview quota failure should not block node creation.
  }
}

export function recordWorkflowCatalogRecent(
  preferences: WorkflowCatalogPreferences,
  typeId: string,
): WorkflowCatalogPreferences {
  const value = String(typeId || '').trim()
  if (!value) return { recent: [...preferences.recent], favorites: [...preferences.favorites] }
  return {
    recent: [value, ...preferences.recent.filter((item) => item !== value)].slice(0, MAX_RECENT),
    favorites: [...preferences.favorites],
  }
}

export function toggleWorkflowCatalogFavorite(
  preferences: WorkflowCatalogPreferences,
  typeId: string,
): WorkflowCatalogPreferences {
  const value = String(typeId || '').trim()
  if (!value) return { recent: [...preferences.recent], favorites: [...preferences.favorites] }
  const favorites = preferences.favorites.includes(value)
    ? preferences.favorites.filter((item) => item !== value)
    : [...preferences.favorites, value]
  return { recent: [...preferences.recent], favorites }
}

/**
 * Normalize the two common schema shapes:
 * - backend JSON schema: { properties, required }
 * - ComfyUI-style object-info: { required: {...}, optional: {...} }
 * Direct maps and tuple descriptors are accepted for old/custom schemas.
 */
export function schemaFields(
  schema: WorkflowNodeSchema | null | undefined,
  direction: 'input' | 'output' = 'input',
): NormalizedSchemaField[] {
  if (!schema) return []
  const source = direction === 'input'
    ? (schema.input_schema ?? schema.input ?? {})
    : (schema.output_schema ?? schema.output ?? {})
  if (!source || typeof source !== 'object' || Array.isArray(source)) return []
  const root = source as Record<string, unknown>
  const result: NormalizedSchemaField[] = []
  const requiredNames = new Set<string>()

  const properties = root.properties
  if (Array.isArray(root.required)) {
    for (const name of root.required) if (typeof name === 'string') requiredNames.add(name)
  }
  if (properties && typeof properties === 'object' && !Array.isArray(properties)) {
    appendEntries(properties as Record<string, unknown>, true)
  } else if (isRecord(root.required) || isRecord(root.optional)) {
    if (isRecord(root.required)) appendEntries(root.required, true)
    if (isRecord(root.optional)) appendEntries(root.optional, false)
  } else {
    appendEntries(root, false)
  }

  function appendEntries(entries: Record<string, unknown>, requiredByGroup: boolean): void {
    for (const [name, descriptor] of Object.entries(entries)) {
      if (name === 'properties' || name === 'required' || name === 'optional') continue
      const field = normalizeSchemaField(name, descriptor, requiredByGroup || requiredNames.has(name))
      if (!result.some((item) => item.name === field.name)) result.push(field)
    }
  }

  return result
}

function normalizeSchemaField(name: string, descriptor: unknown, required: boolean): NormalizedSchemaField {
  let rawType: unknown = descriptor
  let metadata: Record<string, unknown> = {}
  if (Array.isArray(descriptor)) {
    rawType = descriptor[0]
    if (isRecord(descriptor[1])) metadata = descriptor[1]
  } else if (isRecord(descriptor)) {
    metadata = descriptor
    rawType = descriptor.type ?? descriptor.value_type ?? descriptor.kind ?? 'any'
  }
  const type = normalizeSchemaType(rawType)
  const enumValue = metadata.enum ?? metadata.options ?? metadata.choices
  return {
    ...metadata,
    name,
    type,
    required,
    ...(Array.isArray(enumValue) ? { enum: enumValue } : {}),
  }
}

/** Collapse common ComfyUI/Python aliases to the workflow port/value types. */
export function normalizeSchemaType(value: unknown): string {
  const lower = String(value || 'any').trim().toLowerCase()
  if (['str', 'string', 'text', 'multiline', 'prompt'].includes(lower)) return 'string'
  if (['int', 'integer', 'float', 'number', 'decimal'].includes(lower)) return 'number'
  if (['bool', 'boolean'].includes(lower)) return 'boolean'
  if (['dict', 'json', 'object'].includes(lower)) return 'object'
  if (['list', 'array', 'tuple'].includes(lower)) return 'array'
  if (['image', 'latent', 'conditioning', 'model', 'clip', 'vae', 'any', '*'].includes(lower)) return 'any'
  return ['string', 'number', 'boolean', 'object', 'array', 'any'].includes(lower) ? lower : 'any'
}

/**
 * Merge schema ports with a node's explicit ports. Existing ports are retained
 * (specialized editors and legacy files remain stable); missing schema fields
 * are appended, which gives new/custom node types useful handles immediately.
 */
export function schemaPorts(
  schema: WorkflowNodeSchema | null | undefined,
  existing: WorkflowPort[] = [],
): WorkflowPort[] {
  if (!schema) return existing.map((port) => ({ ...port }))
  const inputs = schemaFields(schema, 'input')
  const outputs = schemaFields(schema, 'output')
  if (!inputs.length && !outputs.length) return existing.map((port) => ({ ...port }))
  const ports = existing.map((port) => ({ ...port }))
  const append = (field: NormalizedSchemaField, direction: 'in' | 'out') => {
    if (ports.some((port) => port.direction === direction && port.name === field.name)) return
    ports.push({
      name: field.name,
      type: field.type,
      direction,
      ...(field.description ? { description: field.description } : {}),
      ...(direction === 'out' && field.default !== undefined ? { value: field.default } : {}),
    })
  }
  inputs.forEach((field) => append(field, 'in'))
  outputs.forEach((field) => append(field, 'out'))
  // Some object-info responses expose output names separately from output map.
  for (const [index, name] of (schema.output_name ?? []).entries()) {
    const outputName = String(name || '').trim()
    if (!outputName) continue
    append({ name: outputName, type: (schema.output_is_list?.[index] ? 'array' : 'any'), required: false }, 'out')
  }
  return ports
}

export function schemaDefaultConfig(schema: WorkflowNodeSchema | null | undefined): Record<string, unknown> {
  const config: Record<string, unknown> = {}
  for (const field of schemaFields(schema, 'input')) {
    if (field.default !== undefined) config[field.name] = field.default
    else if (field.enum?.length) config[field.name] = field.enum[0]
    else if (field.type === 'boolean') config[field.name] = false
    else if (field.type === 'number') config[field.name] = 0
    else if (field.type === 'object') config[field.name] = {}
    else if (field.type === 'array') config[field.name] = []
    else config[field.name] = ''
  }
  return config
}

/** Build a node from object-info while retaining the five built-in editor kinds. */
export function createWorkflowNodeFromSchema(
  schema: WorkflowNodeSchema,
  id: string,
  position: { x: number; y: number },
): WorkflowNode {
  const typeId = workflowNodeTypeId(schema)
  const kind = workflowNodeKindForTypeId(typeId)
  const config: Record<string, unknown> = {
    ...schemaDefaultConfig(schema),
    ...(kind === 'ai' ? { instruction: '', mode: 'single' } : {}),
    ...(kind === 'model' ? { instruction: '', model_id: '' } : {}),
    ...(kind === 'agent' ? { instruction: '', model_id: '' } : {}),
    ...(kind === 'command' ? { command: '' } : {}),
    ...(kind === 'script' || kind === 'python' ? { script: '' } : {}),
    ...(kind === 'content' || kind === 'constant' ? { value: '' } : {}),
    ...(kind === 'subgraph' ? { workflow_name: '', iterate: 'none' } : {}),
  }
  const ports = schemaPorts(schema)
  if (!ports.length) {
    ports.push(
      ...(['content', 'constant', 'input'].includes(String(kind))
        ? [{ name: 'out', type: 'any', direction: 'out' as const, value: '' }]
        : [
            { name: 'in', type: 'any', direction: 'in' as const },
            { name: 'out', type: 'any', direction: 'out' as const },
          ]),
    )
  }
  return {
    id,
    kind,
    title: workflowNodeDisplayName(schema, id),
    config,
    ports,
    position,
    ...(typeId ? { type_id: typeId } : {}),
    ...(schema.type_version !== undefined ? { type_version: Math.max(1, Number(schema.type_version) || 1) } : {}),
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function normalizeStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? [...new Set(value.map((item) => String(item || '').trim()).filter(Boolean))]
    : []
}
