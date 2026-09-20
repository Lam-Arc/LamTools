export type Assessment = 'unassessed' | 'pass' | 'fail'
export type Mastery = 'low' | 'medium' | 'high'
export type ProgressRole = 'unit' | 'aggregate' | 'none'
export type NodeKind = 'course' | 'module' | 'concept' | 'theorem' | 'formula' | 'method' | 'skill' | 'topic' | string

/**
 * Study DTOs are intentionally tolerant at the UI boundary.  The current
 * host still returns a few snake_case legacy fields while the v2 contract
 * uses camelCase.  `study/api.ts` normalises both into these fields and keeps
 * the legacy aliases only for old plugins/tests.
 */
export interface KnowledgeItem {
  id: string
  name: string
  title?: string
  entity?: 'module' | 'node' | 'course' | 'concept' | 'topic' | string
  kind?: NodeKind
  learnable: boolean
  progressRole: ProgressRole
  progress_role?: string
  assessment: Assessment
  mastery: Mastery | null
  passed?: boolean
  evaluated?: boolean
  total?: number
  course_id?: string
  parent_id?: string
  childCount?: number
  child_count?: number
  scope?: string
  structureRevision?: number
  structure_revision?: number
  stateRevision?: number
  state_revision?: number
  revision?: number
  [key: string]: unknown
}

export interface Course {
  id: string
  name: string
  total: number
  passed: number
  structureRevision?: number
  stateRevision?: number
  [key: string]: unknown
}

export interface Relation {
  id: string
  source: string
  target: string
  type: string
  reason?: string
  contextId?: string | null
  context_id?: string | null
  order?: number | null
}

export interface Net {
  revision: number
  structureRevision?: number
  structure_revision?: number
  stateRevision?: number
  state_revision?: number
  scope?: unknown
  courses?: Course[]
  course?: Course
  module?: KnowledgeItem
  node?: KnowledgeItem
  items?: KnowledgeItem[]
  relations?: Relation[]
  neighbors?: KnowledgeItem[]
  total: number
  current?: KnowledgeItem | null
  progress?: { total: number; passed: number; covered?: number }
  hasMore?: boolean
  has_more?: boolean
  nextCursor?: string | null
  next_cursor?: string | null
  partial?: boolean
  omittedReason?: string | null
  omitted_reason?: string | null
}

export type StudySubject =
  | { kind: 'map'; id: string }
  | { kind: 'notes'; id: string }
  | { kind: 'node'; id: string }

export interface SessionBinding {
  libraryId?: string
  library_id?: string
  subject: StudySubject
  sessionId: string
  session_id?: string
  isPrimary: boolean
  is_primary?: boolean
  draft?: string | null
  hasDraft?: boolean
  has_draft?: boolean
}

export interface StudyPin {
  id: string
  kind: 'node' | 'note' | 'session'
  title: string
}

export interface MarkAnchor {
  document_id: string
  block_id: string
  sourceId?: string
  blockId?: string
  start: number
  end: number
  quote: string
  prefix: string
  suffix: string
  session_id?: string
  source_type?: string
  source_id?: string
  source_revision?: number
  sourceRevision?: number
  projection_version?: 'semantic-text-v1' | string
  projectionVersion?: 'semantic-text-v1' | string
  unit?: 'unicode-code-point' | 'utf-16' | string
  segments?: Array<{
    start: number
    end: number
    exact: string
    prefix: string
    suffix: string
    block_id?: string
  }>
  page?: number
  rects?: number[][]
}

export interface StudyDictionaryEntry {
  word: string
  phonetic: string
  pos: string
  zh: string
  en: string
  example: string
}

export interface StudyMark {
  id: string
  anchor: MarkAnchor
  prompt_version?: number
  explain: string
  translate: string
  dictionary?: StudyDictionaryEntry | null
  thread: Array<{ role: 'user' | 'assistant'; content: string }>
  sourceNodeIds?: string[]
  state?: 'resolved' | 'needs_location' | 'source_removed'
}

export type TextAction = 'mark' | 'explain' | 'translate' | 'ask'

/** A first-class piece of evidence available to a Markdown note. */
export interface StudyNoteResource {
  id: string
  title?: string
  kind?: string
  type?: string
  originalType?: string
  original_type?: string
  locator?: string
  revision?: number
  [key: string]: unknown
}

/** An Agent protection range inside a Markdown document. */
export interface StudyNoteLock {
  id: string
  start: number
  end: number
  quote: string
  reason?: string
  owner?: 'user' | 'agent' | string
  createdAt?: string
  created_at?: string
  overlap?: { start: number; end: number; quote?: string } | null
  [key: string]: unknown
}

export type StudyNoteTreeKind = 'folder' | 'note'

export interface StudyNoteTreeNode {
  id: string
  title: string
  path: string
  kind: StudyNoteTreeKind
  parent?: string | null
  children?: StudyNoteTreeNode[]
  noteId?: string
  note_id?: string
  hasChildren?: boolean
  expanded?: boolean
  [key: string]: unknown
}

export interface StudyNoteGraphNode {
  id: string
  title: string
  path?: string
  kind: 'note' | string
  parent?: string | null
  [key: string]: unknown
}

export interface StudyNoteGraphEdge {
  id: string
  source: string
  target: string
  type?: 'wikilink' | 'parent' | string
  label?: string
  [key: string]: unknown
}

export interface StudyNoteGraph {
  revision: number
  nodes: StudyNoteGraphNode[]
  edges: StudyNoteGraphEdge[]
}

/**
 * A note link is intentionally tolerant at the UI boundary.  Older Study
 * payloads returned a bare target string while newer payloads may include a
 * target kind and a display label.  `normalizeNote` canonicalises both forms
 * without discarding unknown fields from the service.
 */
export interface StudyNoteLink {
  target: string
  id?: string
  label?: string
  title?: string
  kind?: 'note' | 'node' | 'unresolved' | string
  [key: string]: unknown
}

export interface StudyNoteBacklink {
  target: string
  id?: string
  noteId?: string
  note_id?: string
  label?: string
  title?: string
  kind?: 'note' | 'node' | 'unresolved' | string
  [key: string]: unknown
}

export interface StudyNote {
  id: string
  libraryId?: string
  library_id?: string
  title: string
  /** Relative path of the actual Markdown file in the note vault. */
  path: string
  /** Semantic parent Markdown document id; directories are represented by path. */
  parent?: string | null
  parent_id?: string | null
  /** The user-facing document body. This is the only editable document text. */
  bodyMd: string
  body_md?: string
  contentHash: string
  content_hash?: string
  resources: StudyNoteResource[]
  resource_ids?: string[]
  locks: StudyNoteLock[]
  nodeIds: string[]
  node_ids?: string[]
  nodeLabels: Record<string, string>
  node_labels?: Record<string, string>
  links: StudyNoteLink[]
  backlinks?: StudyNoteBacklink[]
  revision: number
}
