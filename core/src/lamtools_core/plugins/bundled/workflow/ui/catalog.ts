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
  'template', 'condition', 'merge', 'join', 'subgraph',
] as const

/** Registry entries that are compatibility aliases, not new-node choices. */
export const WORKFLOW_HIDDEN_NODE_KINDS = [...WORKFLOW_LEGACY_NODE_KINDS] as string[]

export function workflowNodeTypeId(schema: WorkflowNodeSchema | null | undefined, fallback = ''): string {
  return String(schema?.type_id ?? schema?.name ?? fallback).trim()
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
    title: String(schema.display_name ?? schema.title ?? schema.name ?? id),
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
