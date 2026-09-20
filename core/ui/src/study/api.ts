import type {
  Assessment,
  Course,
  KnowledgeItem,
  MarkAnchor,
  Mastery,
  Net,
  Relation,
  SessionBinding,
  StudyDictionaryEntry,
  StudyMark,
  StudyNoteBacklink,
  StudyNoteGraph,
  StudyNoteGraphEdge,
  StudyNoteGraphNode,
  StudyNoteLock,
  StudyNoteLink,
  StudyNoteResource,
  StudyNoteTreeNode,
  StudyNote,
  StudySubject,
} from './types'

export type StudyRpc = (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function number(value: unknown, fallback = 0): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function bool(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map(item => typeof item === 'string' ? item.trim() : text(item)).filter(Boolean)
    : []
}

function stringMap(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {}
  return Object.fromEntries(Object.entries(value)
    .map(([key, label]) => [key.trim(), text(label).trim()])
    .filter(([key, label]) => Boolean(key && label)))
}

function linkKind(value: unknown): StudyNoteLink['kind'] | undefined {
  const kind = text(value).trim().toLowerCase()
  return kind === 'note' || kind === 'node' || kind === 'unresolved' ? kind : (kind || undefined)
}

/** Normalize legacy string and v2 object link payloads without losing fields. */
export function normalizeNoteLink(value: unknown): StudyNoteLink {
  if (typeof value === 'string') {
    const target = value.trim()
    return { target, id: target || undefined, label: target || undefined }
  }
  const raw = isRecord(value) ? value : {}
  const target = text(raw.target || raw.note_id || raw.noteId || raw.node_id || raw.nodeId || raw.id || raw.title || raw.label).trim()
  const id = text(raw.id || raw.note_id || raw.noteId || raw.node_id || raw.nodeId || target).trim()
  const label = text(raw.label || raw.title || target).trim()
  return {
    ...raw,
    target,
    id: id || undefined,
    label: label || undefined,
    title: text(raw.title).trim() || undefined,
    kind: linkKind(raw.kind || raw.entity_type || raw.entityType),
  }
}

export function normalizeNoteBacklink(value: unknown): StudyNoteBacklink {
  if (typeof value === 'string') {
    const target = value.trim()
    return { target, id: target || undefined, noteId: target || undefined, label: target || undefined }
  }
  const raw = isRecord(value) ? value : {}
  // Backlink rows often carry `target` for the note currently being viewed;
  // the navigable note is the backlink's own note_id.  Keep the source target
  // in the spread fields, but make the canonical target point at note_id.
  const target = text(raw.note_id || raw.noteId || raw.id || raw.target || raw.title || raw.label).trim()
  const id = text(raw.id || raw.note_id || raw.noteId || target).trim()
  const label = text(raw.title || raw.label || target).trim()
  return {
    ...raw,
    target,
    id: id || undefined,
    noteId: text(raw.noteId || raw.note_id || id).trim() || undefined,
    note_id: text(raw.note_id || raw.noteId || id).trim() || undefined,
    label: label || undefined,
    title: text(raw.title).trim() || undefined,
    kind: linkKind(raw.kind || raw.entity_type || raw.entityType) || 'note',
  }
}

function nodeIdsFrom(value: unknown): string[] {
  if (!isRecord(value)) return []
  return stringList(value.nodeIds || value.node_ids)
}

function noteNodeIds(raw: Record<string, unknown>): string[] {
  const ids = new Set<string>()
  for (const id of [...nodeIdsFrom(raw), ...nodeIdsFrom(raw.source)]) ids.add(id)
  const resources = [raw.sources, raw.resources, raw.resource_refs, raw.resourceRefs]
  for (const value of resources) {
    const rows = Array.isArray(value) ? value : value ? [value] : []
    for (const resource of rows) for (const id of nodeIdsFrom(resource)) ids.add(id)
  }
  return [...ids]
}

export interface StudyMarkdownHeading {
  level: 1 | 2 | 3 | 4 | 5 | 6
  text: string
  id: string
}

function headingSlug(value: string, index: number, seen: Map<string, number>): string {
  const base = value
    .trim()
    .toLocaleLowerCase()
    .replace(/[`*_~]/g, '')
    .replace(/[^\w\u00a0-\uffff-]+/g, '-')
    .replace(/^-+|-+$/g, '') || `heading-${index + 1}`
  const count = seen.get(base) || 0
  seen.set(base, count + 1)
  return count ? `${base}-${count + 1}` : base
}

/** Extract h1-h6 headings for the Study note outline without parsing a second Markdown AST. */
export function extractMarkdownHeadings(markdown: string): StudyMarkdownHeading[] {
  const result: StudyMarkdownHeading[] = []
  const seen = new Map<string, number>()
  let fenced = false
  const lines = String(markdown || '').replace(/\r\n?/g, '\n').split('\n')
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const fence = line.match(/^\s{0,3}(```+|~~~+)/)
    if (fence) { fenced = !fenced; continue }
    if (fenced) continue
    const match = line.match(/^\s{0,3}(#{1,6})(?:[ \t]+(.+))?\s*$/)
    if (match) {
      const level = match[1].length as 1 | 2 | 3 | 4 | 5 | 6
      const headingText = (match[2] || '').replace(/[ \t]+#+[ \t]*$/g, '').trim()
      if (headingText) result.push({ level, text: headingText, id: headingSlug(headingText, result.length, seen) })
      continue
    }
    // Marked also renders CommonMark setext headings. Keep this fallback for
    // callers that need a lightweight outline before a renderer is mounted;
    // NotesManager still derives its final IDs from rendered DOM nodes.
    const underline = lines[index + 1]?.match(/^\s{0,3}(=+|-+)\s*$/)
    const headingText = line.trim()
    if (underline && headingText) {
      const level = underline[1][0] === '=' ? 1 : 2
      result.push({ level, text: headingText, id: headingSlug(headingText, result.length, seen) })
      index += 1
    }
  }
  return result
}

function assessmentOf(raw: Record<string, unknown>, fallbackEntity = ''): Assessment {
  const value = text(raw.assessment)
  if (value === 'pass' || value === 'fail' || value === 'unassessed') return value
  if (bool(raw.passed)) return 'pass'
  if (bool(raw.evaluated) || raw.evaluated === true) return 'fail'
  return fallbackEntity === 'module' || fallbackEntity === 'course' ? 'unassessed' : 'unassessed'
}

function masteryOf(raw: Record<string, unknown>, assessment: Assessment): Mastery | null {
  const value = text(raw.mastery)
  if (assessment !== 'pass') return null
  return value === 'low' || value === 'medium' || value === 'high' ? value : null
}

function progressRoleOf(raw: Record<string, unknown>, entity: string): KnowledgeItem['progressRole'] {
  const rawRole = text(raw.progressRole || raw.progress_role)
  if (rawRole === 'aggregate' || rawRole === 'unit' || rawRole === 'none') return rawRole
  // The legacy backend called this field "assessed".  It means an atomic
  // learning target for a node, not a fourth public progress role.
  if (rawRole === 'assessed') return entity === 'module' || entity === 'course' ? 'none' : 'unit'
  return entity === 'module' || entity === 'course' ? 'none' : 'unit'
}

export function normalizeKnowledgeItem(value: unknown, fallbackEntity = 'node'): KnowledgeItem {
  const raw = isRecord(value) ? value : {}
  const entity = text(raw.entity || raw.kind, fallbackEntity) || fallbackEntity
  const assessment = assessmentOf(raw, entity)
  const id = text(raw.id || raw.node_id || raw.nodeId)
  const name = text(raw.name || raw.title, id)
  return {
    ...raw,
    id,
    name,
    title: text(raw.title, name),
    entity: entity as KnowledgeItem['entity'],
    kind: text(raw.kind, entity),
    learnable: bool(raw.learnable, entity !== 'module' && entity !== 'course'),
    progressRole: progressRoleOf(raw, entity),
    progress_role: text(raw.progress_role || raw.progressRole, progressRoleOf(raw, entity)),
    assessment,
    mastery: masteryOf(raw, assessment),
    passed: bool(raw.passed, assessment === 'pass'),
    evaluated: bool(raw.evaluated, assessment !== 'unassessed'),
    childCount: number(raw.childCount ?? raw.child_count, 0),
    child_count: number(raw.child_count ?? raw.childCount, 0),
    structureRevision: number(raw.structureRevision ?? raw.structure_revision ?? raw.revision, 0),
    structure_revision: number(raw.structure_revision ?? raw.structureRevision ?? raw.revision, 0),
    stateRevision: number(raw.stateRevision ?? raw.state_revision, 0),
    state_revision: number(raw.state_revision ?? raw.stateRevision, 0),
  }
}

export function normalizeCourse(value: unknown): Course {
  const raw = isRecord(value) ? value : {}
  return {
    ...raw,
    id: text(raw.id || raw.course_id),
    name: text(raw.name || raw.title || raw.id),
    total: number(raw.total, 0),
    passed: number(raw.passed, 0),
    structureRevision: number(raw.structureRevision ?? raw.structure_revision ?? raw.revision, 0),
    stateRevision: number(raw.stateRevision ?? raw.state_revision, 0),
  }
}

export function normalizeRelation(value: unknown): Relation {
  const raw = isRecord(value) ? value : {}
  return {
    ...raw,
    id: text(raw.id || raw.relation_id),
    source: text(raw.source || raw.from || raw.from_id),
    target: text(raw.target || raw.to || raw.to_id),
    type: text(raw.type || raw.kind, 'related'),
    reason: text(raw.reason),
    contextId: (raw.contextId ?? raw.context_id ?? null) as string | null,
    context_id: (raw.context_id ?? raw.contextId ?? null) as string | null,
    order: raw.order == null ? null : number(raw.order),
  }
}

export function normalizeNet(value: unknown): Net {
  const raw = isRecord(value) ? value : {}
  const items = Array.isArray(raw.items)
    ? raw.items.map(item => normalizeKnowledgeItem(item, isRecord(item) && text(item.entity) ? text(item.entity) : 'node'))
    : []
  const courses = Array.isArray(raw.courses) ? raw.courses.map(normalizeCourse) : []
  return {
    ...raw,
    revision: number(raw.revision ?? raw.structure_revision, 0),
    structureRevision: number(raw.structureRevision ?? raw.structure_revision ?? raw.revision, 0),
    structure_revision: number(raw.structure_revision ?? raw.structureRevision ?? raw.revision, 0),
    stateRevision: number(raw.stateRevision ?? raw.state_revision, 0),
    state_revision: number(raw.state_revision ?? raw.stateRevision, 0),
    courses,
    course: raw.course ? normalizeCourse(raw.course) : undefined,
    module: raw.module ? normalizeKnowledgeItem(raw.module, 'module') : undefined,
    node: raw.node ? normalizeKnowledgeItem(raw.node, 'node') : undefined,
    current: raw.current ? normalizeKnowledgeItem(raw.current, 'node') : null,
    items,
    relations: Array.isArray(raw.relations) ? raw.relations.map(normalizeRelation) : [],
    neighbors: Array.isArray(raw.neighbors) ? raw.neighbors.map(item => normalizeKnowledgeItem(item, 'node')) : [],
    total: number(raw.total, items.length || courses.length),
    hasMore: bool(raw.hasMore ?? raw.has_more),
    has_more: bool(raw.has_more ?? raw.hasMore),
    nextCursor: raw.nextCursor == null && raw.next_cursor == null ? null : text(raw.nextCursor ?? raw.next_cursor),
    next_cursor: raw.next_cursor == null && raw.nextCursor == null ? null : text(raw.next_cursor ?? raw.nextCursor),
    partial: bool(raw.partial),
    omittedReason: raw.omittedReason == null && raw.omitted_reason == null ? null : text(raw.omittedReason ?? raw.omitted_reason),
    omitted_reason: raw.omitted_reason == null && raw.omittedReason == null ? null : text(raw.omitted_reason ?? raw.omittedReason),
  }
}

export function normalizeSubject(value: unknown, fallback: StudySubject): StudySubject {
  const raw = isRecord(value) ? value : {}
  const kind = text(raw.kind || raw.scope || raw.study_scope, fallback.kind)
  const id = text(raw.id || raw.subject_id || raw.node_id || raw.resource_id, fallback.id)
  if (kind === 'node') return { kind: 'node', id }
  if (kind === 'notes') return { kind: 'notes', id: id || 'notes' }
  return { kind: 'map', id: id || 'map' }
}

export function normalizeSessionBinding(value: unknown, fallback: StudySubject): SessionBinding | null {
  const raw = isRecord(value) ? value : {}
  const nested = isRecord(raw.binding) ? raw.binding : isRecord(raw.session) ? raw.session : raw
  const sessionId = text(nested.sessionId || nested.session_id || nested.id)
  if (!sessionId) return null
  const subject = normalizeSubject(nested.subject || nested, fallback)
  return {
    libraryId: text(nested.libraryId || nested.library_id) || undefined,
    library_id: text(nested.library_id || nested.libraryId) || undefined,
    subject,
    sessionId,
    session_id: sessionId,
    isPrimary: nested.isPrimary == null && nested.is_primary == null ? true : bool(nested.isPrimary ?? nested.is_primary),
    is_primary: nested.is_primary == null && nested.isPrimary == null ? true : bool(nested.is_primary ?? nested.isPrimary),
    draft: typeof nested.draft === 'string' ? nested.draft : (typeof nested.draft_text === 'string' ? nested.draft_text : null),
    hasDraft: bool(nested.hasDraft ?? nested.has_draft),
    has_draft: bool(nested.has_draft ?? nested.hasDraft),
  }
}

export function normalizeNoteResource(value: unknown): StudyNoteResource {
  const raw = isRecord(value) ? value : {}
  const id = text(raw.id || raw.resource_id || raw.resourceId || raw.source_id || raw.sourceId)
  const kind = text(raw.kind || raw.type || raw.source_type || raw.sourceType)
  return {
    ...raw,
    id,
    title: text(raw.title || raw.name || raw.label) || undefined,
    kind: kind || undefined,
    type: text(raw.type || raw.kind) || undefined,
    originalType: text(raw.originalType || raw.original_type) || undefined,
    original_type: text(raw.original_type || raw.originalType) || undefined,
    locator: text(raw.locator || raw.url || raw.path) || undefined,
    revision: raw.revision == null ? undefined : number(raw.revision),
  }
}

export function normalizeNoteLock(value: unknown, index = 0): StudyNoteLock {
  const raw = isRecord(value) ? value : {}
  const start = number(raw.start ?? raw.start_offset ?? raw.startOffset)
  const end = number(raw.end ?? raw.end_offset ?? raw.endOffset, start)
  return {
    ...raw,
    id: text(raw.id || raw.lock_id || raw.lockId) || `lock-${index + 1}`,
    start: Math.max(0, start),
    end: Math.max(start, end),
    quote: text(raw.quote || raw.exact || raw.text),
    reason: text(raw.reason || raw.message) || undefined,
    owner: text(raw.owner || raw.author) || undefined,
    createdAt: text(raw.createdAt || raw.created_at) || undefined,
    created_at: text(raw.created_at || raw.createdAt) || undefined,
    overlap: isRecord(raw.overlap) ? {
      start: number(raw.overlap.start ?? raw.overlap.start_offset),
      end: number(raw.overlap.end ?? raw.overlap.end_offset),
      quote: text(raw.overlap.quote || raw.overlap.exact) || undefined,
    } : null,
  }
}

function treeKind(value: unknown): StudyNoteTreeNode['kind'] {
  const kind = text(value).toLocaleLowerCase()
  return kind === 'folder' || kind === 'directory' || kind === 'dir' ? 'folder' : 'note'
}

export function normalizeNoteTreeNode(value: unknown, index = 0): StudyNoteTreeNode {
  const raw = isRecord(value) ? value : {}
  const id = text(raw.id || raw.note_id || raw.noteId || raw.path || `note-${index + 1}`)
  const path = text(raw.path || raw.file_path || raw.filePath || id)
  const title = text(raw.title || raw.name || raw.label || path.split('/').pop()?.replace(/\.md$/i, '') || id)
  const kind = treeKind(raw.kind || raw.type || raw.entity_type || raw.entityType || (Array.isArray(raw.children) ? 'folder' : 'note'))
  const children = Array.isArray(raw.children) ? raw.children.map((child, childIndex) => normalizeNoteTreeNode(child, childIndex)) : undefined
  return {
    ...raw,
    id,
    title,
    path,
    kind,
    parent: raw.parent == null && raw.parent_id == null ? undefined : text(raw.parent || raw.parent_id) || null,
    parent_id: raw.parent_id == null && raw.parent == null ? undefined : text(raw.parent_id || raw.parent) || null,
    noteId: text(raw.noteId || raw.note_id || (kind === 'note' ? id : '')) || undefined,
    note_id: text(raw.note_id || raw.noteId || (kind === 'note' ? id : '')) || undefined,
    children,
    hasChildren: raw.hasChildren == null && raw.has_children == null ? Boolean(children?.length) : Boolean(raw.hasChildren ?? raw.has_children),
  }
}

export function normalizeNoteTree(value: unknown): StudyNoteTreeNode[] {
  if (Array.isArray(value)) return value.map((row, index) => normalizeNoteTreeNode(row, index))
  if (!isRecord(value)) return []
  const rows = value.tree ?? value.files ?? value.notes ?? value.items ?? value.children
  return Array.isArray(rows) ? rows.map((row, index) => normalizeNoteTreeNode(row, index)) : []
}

export function normalizeNoteGraphNode(value: unknown, index = 0): StudyNoteGraphNode {
  const raw = isRecord(value) ? value : {}
  const id = text(raw.id || raw.note_id || raw.noteId || `note-${index + 1}`)
  return {
    ...raw,
    id,
    title: text(raw.title || raw.name || raw.label || id),
    path: text(raw.path || raw.file_path || raw.filePath) || undefined,
    kind: text(raw.kind || raw.type || raw.entity_type || raw.entityType, 'note'),
    parent: raw.parent == null && raw.parent_id == null ? undefined : text(raw.parent || raw.parent_id) || null,
  }
}

export function normalizeNoteGraphEdge(value: unknown, index = 0): StudyNoteGraphEdge {
  const raw = isRecord(value) ? value : {}
  return {
    ...raw,
    id: text(raw.id || raw.edge_id || `edge-${index + 1}`),
    source: text(raw.source || raw.from || raw.from_id || raw.fromId),
    target: text(raw.target || raw.to || raw.to_id || raw.toId),
    // Graph rows from the Study service use `kind`; normalize it to the UI's
    // stable `type` field while retaining the raw value above.
    type: text(raw.type || raw.kind, 'wikilink'),
    label: text(raw.label || raw.title) || undefined,
  }
}

export function normalizeNoteGraph(value: unknown): StudyNoteGraph {
  const raw = isRecord(value) ? value : {}
  const nodes = Array.isArray(raw.nodes) ? raw.nodes.map((node, index) => normalizeNoteGraphNode(node, index)) : []
  const rawEdges = raw.edges ?? raw.links ?? raw.relations
  const edges = Array.isArray(rawEdges)
    ? (rawEdges as unknown[]).map((edge, index) => normalizeNoteGraphEdge(edge, index))
    : []
  return { revision: number(raw.revision ?? raw.graph_revision, 0), nodes, edges }
}

export function normalizeNote(value: unknown): StudyNote {
  const raw = isRecord(value) ? value : {}
  const nodeIds = noteNodeIds(raw)
  const nodeLabels = stringMap(raw.nodeLabels || raw.node_labels)
  // A note is one Markdown document.  Do not reconstruct it from legacy
  // block rows or accept another content field as a second source of truth.
  const bodyMd = typeof raw.bodyMd === 'string' ? raw.bodyMd : text(raw.body_md)
  const resourcesRaw = raw.resources || raw.resource_refs || raw.resourceRefs || raw.sources || raw.source
  const resources = Array.isArray(resourcesRaw)
    ? resourcesRaw.map(normalizeNoteResource).filter(resource => Boolean(resource.id || resource.title))
    : resourcesRaw ? [normalizeNoteResource(resourcesRaw)].filter(resource => Boolean(resource.id || resource.title)) : []
  const rawResourceIds = raw.resource_ids ?? raw.resourceIds
  const resourceIds = Array.isArray(rawResourceIds)
    ? (rawResourceIds as unknown[]).map(String).filter(Boolean)
    : resources.map(resource => resource.id).filter(Boolean)
  const materializedResources = resourceIds.map(id => resources.find(resource => resource.id === id) || ({ id, title: id, kind: 'resource' } as StudyNoteResource))
  const rawLocks = raw.locks ?? raw.lock_ranges ?? raw.lockRanges
  const path = text(raw.path || raw.file_path || raw.filePath || raw.id)
  const parent = raw.parent == null && raw.parent_id == null ? undefined : text(raw.parent || raw.parent_id) || null
  return {
    ...raw,
    id: text(raw.id || raw.note_id),
    libraryId: text(raw.libraryId || raw.library_id) || undefined,
    library_id: text(raw.library_id || raw.libraryId) || undefined,
    title: text(raw.title || raw.name || raw.id),
    path,
    parent,
    parent_id: raw.parent_id == null && raw.parent == null ? undefined : text(raw.parent_id || raw.parent) || null,
    bodyMd,
    body_md: bodyMd,
    contentHash: text(raw.contentHash || raw.content_hash || raw.hash),
    content_hash: text(raw.content_hash || raw.contentHash || raw.hash),
    resources: materializedResources,
    resource_ids: resourceIds,
    locks: Array.isArray(rawLocks)
      ? (rawLocks as unknown[]).map((lock, index) => normalizeNoteLock(lock, index))
      : [],
    nodeIds,
    node_ids: nodeIds,
    nodeLabels,
    node_labels: nodeLabels,
    links: Array.isArray(raw.links) ? raw.links.map(normalizeNoteLink).filter(link => Boolean(link.target)) : [],
    backlinks: Array.isArray(raw.backlinks) ? raw.backlinks.map(normalizeNoteBacklink).filter(link => Boolean(link.target)) : [],
    revision: number(raw.revision, 0),
  }
}

export function normalizeDictionary(value: unknown): StudyDictionaryEntry | null {
  if (!isRecord(value)) return null
  return {
    word: text(value.word),
    phonetic: text(value.phonetic),
    pos: text(value.pos),
    zh: text(value.zh),
    en: text(value.en),
    example: text(value.example),
  }
}

export function normalizeAnchor(value: unknown): MarkAnchor {
  const raw = isRecord(value) ? value : {}
  const segments = Array.isArray(raw.segments)
    ? raw.segments.filter(isRecord).map(segment => ({
      start: number(segment.start), end: number(segment.end), exact: text(segment.exact),
      prefix: text(segment.prefix), suffix: text(segment.suffix),
      block_id: text(segment.block_id || segment.blockId) || undefined,
    }))
    : undefined
  return {
    document_id: text(raw.document_id || raw.sourceId || raw.source_id),
    block_id: text(raw.block_id || raw.blockId),
    sourceId: text(raw.sourceId || raw.source_id || raw.document_id) || undefined,
    blockId: text(raw.blockId || raw.block_id) || undefined,
    start: number(raw.start),
    end: number(raw.end),
    quote: text(raw.quote || raw.exact),
    prefix: text(raw.prefix),
    suffix: text(raw.suffix),
    session_id: text(raw.session_id || raw.sessionId) || undefined,
    source_type: text(raw.source_type || raw.sourceType) || undefined,
    source_id: text(raw.source_id || raw.sourceId) || undefined,
    source_revision: raw.source_revision == null && raw.sourceRevision == null ? undefined : number(raw.source_revision ?? raw.sourceRevision),
    sourceRevision: raw.sourceRevision == null && raw.source_revision == null ? undefined : number(raw.sourceRevision ?? raw.source_revision),
    projection_version: text(raw.projection_version || raw.projectionVersion) as MarkAnchor['projection_version'] || undefined,
    projectionVersion: text(raw.projectionVersion || raw.projection_version) as MarkAnchor['projectionVersion'] || undefined,
    // Legacy marks were persisted from browser Selection offsets (UTF-16).
    // New marks always carry the explicit Unicode code-point unit; retaining
    // the old default keeps existing highlights relocatable after upgrade.
    unit: text(raw.unit, raw.projection_version || raw.projectionVersion ? 'unicode-code-point' : 'utf-16') as MarkAnchor['unit'],
    segments,
    page: raw.page == null ? undefined : number(raw.page),
    rects: Array.isArray(raw.rects) ? raw.rects as number[][] : undefined,
  }
}

export function normalizeMark(value: unknown): StudyMark {
  const raw = isRecord(value) ? value : {}
  const thread = Array.isArray(raw.thread)
    ? raw.thread.filter(isRecord).map(turn => ({ role: text(turn.role) === 'user' ? 'user' as const : 'assistant' as const, content: text(turn.content) }))
    : []
  const state = text(raw.state)
  return {
    ...raw,
    id: text(raw.id),
    anchor: normalizeAnchor(raw.anchor),
    prompt_version: raw.prompt_version == null && raw.promptVersion == null ? undefined : number(raw.prompt_version ?? raw.promptVersion),
    explain: text(raw.explain),
    translate: text(raw.translate),
    dictionary: normalizeDictionary(raw.dictionary),
    thread,
    sourceNodeIds: Array.isArray(raw.sourceNodeIds) ? raw.sourceNodeIds.map(String) : (Array.isArray(raw.source_node_ids) ? raw.source_node_ids.map(String) : undefined),
    state: state === 'needs_location' || state === 'source_removed' || state === 'resolved' ? state : undefined,
  }
}

/**
 * Invoke a read-only Study endpoint with compatibility aliases.  Mutation
 * paths deliberately call one concrete method and must not be retried here.
 */
export async function requestStudyRead(
  rpc: StudyRpc,
  methods: string[],
  params: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  let lastError: unknown
  for (const method of methods) {
    try {
      return await rpc(method, params)
    } catch (error) {
      lastError = error
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError || 'Study RPC unavailable'))
}

export function subjectParams(subject: StudySubject): Record<string, unknown> {
  return {
    subject: { kind: subject.kind, id: subject.id },
    subject_kind: subject.kind,
    subject_id: subject.id,
    scope: subject.kind,
    ...(subject.kind === 'node' ? { node_id: subject.id } : {}),
  }
}
