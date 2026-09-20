import { onBeforeUnmount, ref } from 'vue'
import {
  normalizeNote,
  normalizeNoteGraph,
  normalizeNoteTree,
  type StudyRpc,
} from './api'
import type {
  StudyNote,
  StudyNoteGraph,
  StudyNoteLock,
  StudyNoteTreeNode,
} from './types'

export interface NoteDocumentSaveMeta {
  revision?: number
  contentHash?: string
  resourceIds?: string[]
}
export interface NoteRange {
  start: number
  end: number
  quote: string
  prefix?: string
  suffix?: string
}

/**
 * Notes have three independent request lifetimes. A tree refresh must never
 * replace a document that is being opened, and a graph response must never
 * repaint a newer note's relation graph.
 */
export function useStudyNotes(rpc: StudyRpc) {
  const notes = ref<StudyNote[]>([])
  const tree = ref<StudyNoteTreeNode[]>([])
  const selectedNote = ref<StudyNote | null>(null)
  const graph = ref<StudyNoteGraph>({ revision: 0, nodes: [], edges: [] })
  const notesLoading = ref(false)
  const treeLoading = ref(false)
  const detailLoading = ref(false)
  const graphLoading = ref(false)
  const loadingMore = ref(false)
  const notesError = ref('')
  const treeError = ref('')
  const detailError = ref('')
  const graphError = ref('')
  const total = ref(0)
  const hasMore = ref(false)
  let query = ''
  let listGeneration = 0
  let treeGeneration = 0
  let detailGeneration = 0
  let graphGeneration = 0
  let detailTarget: string | null = null
  let graphTarget: string | null = null
  let disposed = false
  let searchTimer: ReturnType<typeof setTimeout> | undefined

  function message(cause: unknown): string {
    if (cause instanceof Error) {
      const errorRecord = cause as Error & { code?: unknown; data?: unknown; reason?: unknown }
      const data = errorRecord.data && typeof errorRecord.data === 'object' ? errorRecord.data as Record<string, unknown> : {}
      const code = String(errorRecord.code || data.code || data.error_code || '').trim()
      const reason = String(errorRecord.reason || data.reason || data.message || cause.message || '').trim()
      return code && reason ? `${code}: ${reason}` : code || reason
    }
    if (typeof cause === 'string') return cause
    if (cause && typeof cause === 'object') {
      const raw = cause as Record<string, unknown>
      const code = String(raw.code || raw.error_code || '').trim()
      const reason = String(raw.reason || raw.message || raw.error || '').trim()
      if (code && reason) return `${code}: ${reason}`
      if (code) return code
      if (reason) return reason
      try { return JSON.stringify(cause) }
      catch { return 'Study RPC unavailable' }
    }
    return String(cause || 'Study RPC unavailable')
  }

  function recordError(cause: unknown): void {
    const raw = message(cause)
    notesError.value = /REVISION_CONFLICT/i.test(raw)
      ? '笔记已有新的修改，未覆盖任何内容。你的草稿已保留，请刷新并核对差异。'
      : raw
  }

  function detailErrorMessage(cause: unknown): string {
    const raw = message(cause)
    if (/REVISION_CONFLICT/i.test(raw)) return '笔记已更新，请刷新后核对；当前草稿已保留。'
    return raw || '未能读取笔记，请重试。'
  }

  async function loadTree(): Promise<void> {
    const token = ++treeGeneration
    treeLoading.value = true
    treeError.value = ''
    try {
      const result = await rpc('study.notes', { action: 'tree' })
      if (disposed || token !== treeGeneration) return
      tree.value = normalizeNoteTree(result.tree ?? result.files ?? result.notes ?? result)
    } catch (cause) {
      if (disposed || token !== treeGeneration) return
      treeError.value = message(cause)
    } finally {
      if (token === treeGeneration) treeLoading.value = false
    }
  }

  async function refreshNoteDetail(noteId: string, fallback: StudyNote | null = null): Promise<StudyNote | null> {
    const token = ++detailGeneration
    detailTarget = noteId
    detailLoading.value = true
    detailError.value = ''
    try {
      const result = await rpc('study.notes', { action: 'get', note_id: noteId })
      if (disposed || token !== detailGeneration) return null
      if (!result.note) throw new Error('未能读取笔记，请重试。')
      const loaded = normalizeNote(result.note)
      selectedNote.value = loaded
      return loaded
    } catch (cause) {
      if (!disposed && token === detailGeneration) {
        detailError.value = detailErrorMessage(cause)
        if (!fallback || selectedNote.value?.id !== noteId) selectedNote.value = null
        else selectedNote.value = fallback
      }
      return null
    } finally {
      if (token === detailGeneration) detailLoading.value = false
    }
  }

  async function loadGraph(noteId?: string): Promise<StudyNoteGraph | null> {
    const token = ++graphGeneration
    graphTarget = noteId || null
    graphLoading.value = true
    graphError.value = ''
    try {
      const result = await rpc('study.notes', { action: 'graph', ...(noteId ? { note_id: noteId } : {}) })
      if (disposed || token !== graphGeneration) return null
      const loaded = normalizeNoteGraph(result.graph ?? result)
      const nodeIds = new Set(loaded.nodes.filter(node => node.kind === 'note' || !node.kind).map(node => node.id))
      graph.value = {
        ...loaded,
        nodes: loaded.nodes.filter(node => node.kind === 'note' || !node.kind),
        edges: loaded.edges.filter(edge => nodeIds.has(edge.source) && nodeIds.has(edge.target)),
      }
      return graph.value
    } catch (cause) {
      if (!disposed && token === graphGeneration) graphError.value = message(cause)
      return null
    } finally {
      if (token === graphGeneration) graphLoading.value = false
    }
  }

  async function selectNote(note: StudyNote | null): Promise<void> {
    notesError.value = ''
    if (!note) {
      ++detailGeneration
      ++graphGeneration
      detailTarget = null
      graphTarget = null
      detailLoading.value = false
      graphLoading.value = false
      detailError.value = ''
      graphError.value = ''
      selectedNote.value = null
      graph.value = { revision: 0, nodes: [], edges: [] }
      return
    }
    selectedNote.value = null
    // The right rail displays the overall vault graph. A document selection
    // must not narrow the graph to a one-note subgraph.
    await Promise.all([refreshNoteDetail(note.id), loadGraph()])
  }

  async function retryNoteDetail(): Promise<void> {
    const target = detailTarget
    if (!target) return
    await refreshNoteDetail(target, selectedNote.value?.id === target ? selectedNote.value : null)
  }

  async function loadNotes(append = false): Promise<void> {
    if (append && (loadingMore.value || notesLoading.value || !hasMore.value)) return
    const token = ++listGeneration
    if (append) loadingMore.value = true
    else notesLoading.value = true
    notesError.value = ''
    const offset = append ? notes.value.length : 0
    try {
      const result = await rpc('study.notes', { action: 'list', q: query, offset, limit: 50 })
      if (disposed || token !== listGeneration) return
      const rows = Array.isArray(result.notes) ? result.notes.map(normalizeNote) : []
      notes.value = append ? [...notes.value, ...rows.filter(row => !notes.value.some(note => note.id === row.id))] : rows
      total.value = typeof result.total === 'number' ? result.total : notes.value.length
      hasMore.value = result.has_more === true || result.hasMore === true
    } catch (cause) {
      if (!disposed && token === listGeneration) recordError(cause)
    } finally {
      if (token === listGeneration) { notesLoading.value = false; loadingMore.value = false }
    }
  }

  async function refreshNotes(): Promise<void> {
    const target = detailTarget
    const note = target ? notes.value.find(candidate => candidate.id === target) || selectedNote.value : selectedNote.value
    // The Note relation graph belongs to the workspace right rail, not to a
    // selected document.  Load it even on the first empty-document visit so
    // the rail is useful before the user opens a file.  A selected document
    // already refreshes the same overall graph through selectNote().
    await Promise.all([loadNotes(), loadTree(), ...(note ? [selectNote(note)] : [loadGraph()])])
  }

  function searchNotes(value: string): void {
    query = value.trim()
    ++listGeneration
    notesLoading.value = true
    loadingMore.value = false
    clearTimeout(searchTimer)
    searchTimer = setTimeout(() => { void loadNotes() }, 200)
  }

  async function saveNoteDocument(note: StudyNote, body: string, meta: NoteDocumentSaveMeta = {}): Promise<StudyNote | null> {
    const content = String(body ?? '')
    notesError.value = ''
    const payload = {
      action: 'update',
      note_id: note.id,
      body_md: content,
      expected_revision: meta.revision ?? note.revision,
      expected_content_hash: meta.contentHash ?? note.contentHash,
      resource_ids: meta.resourceIds ?? note.resource_ids ?? note.resources.map(resource => resource.id).filter(Boolean),
    }
    try {
      const result = await rpc('study.notes', payload)
      if (result.ok === false || result.saved === false) throw new Error(message(result.error || '未能确认笔记已保存'))
      const acknowledgement = result.note && typeof result.note === 'object' ? result.note as Record<string, unknown> : {}
      const acknowledgedHash = result.content_hash ?? result.contentHash ?? acknowledgement.content_hash ?? acknowledgement.contentHash
      const fallback = normalizeNote({
        ...note,
        body_md: content,
        bodyMd: content,
        content_hash: typeof acknowledgedHash === 'string' ? acknowledgedHash : note.contentHash,
        contentHash: typeof acknowledgedHash === 'string' ? acknowledgedHash : note.contentHash,
        revision: typeof result.revision === 'number' ? result.revision : typeof acknowledgement.revision === 'number' ? acknowledgement.revision : note.revision,
      })
      if (detailTarget === note.id) selectedNote.value = fallback
      const refreshed = await refreshNoteDetail(note.id, fallback)
      // A committed write is authoritative even if the advisory detail read
      // is unavailable. Return the acknowledgement fallback so the editor
      // can advance its revision/hash baseline for the next save.
      return refreshed || fallback
    } catch (cause) {
      if (!disposed) recordError(cause)
      throw cause
    }
  }

  async function createNote(input: { id?: string; title: string; path?: string; parent?: string | null; bodyMd?: string; resourceIds?: string[] }): Promise<StudyNote | null> {
    const result = await rpc('study.notes', {
      action: 'create', note_id: input.id, title: input.title, path: input.path, parent_id: input.parent,
      body_md: input.bodyMd || '', resource_ids: input.resourceIds || [],
    })
    await loadTree()
    const id = String(result.note_id || result.id || input.id || '')
    if (!id) return null
    return refreshNoteDetail(id)
  }

  async function lockRange(note: StudyNote, range: NoteRange): Promise<StudyNoteLock | null> {
    // Textarea/DOM selections are UTF-16 code-unit offsets. Preserve those
    // offsets byte-for-byte so a surrogate pair (emoji) cannot shift a lock.
    const result = await rpc('study.notes', { action: 'lock_range', note_id: note.id, start: range.start, end: range.end, quote: range.quote, unit: 'utf16_code_unit', ...(range.prefix ? { prefix: range.prefix } : {}), ...(range.suffix ? { suffix: range.suffix } : {}) })
    // The mutation response is currently flat ({lock_id,start,end,quote}); a
    // nested {lock:{...}} response remains accepted for forward compatibility.
    const lockValue = result.lock || result
    const lock = lockValue && typeof lockValue === 'object' ? (await import('./api')).normalizeNoteLock(lockValue) : null
    if (lock && selectedNote.value?.id === note.id) selectedNote.value = normalizeNote({ ...selectedNote.value, locks: [...selectedNote.value.locks, lock] })
    return lock
  }

  async function unlockRange(note: StudyNote, lock: StudyNoteLock | string): Promise<void> {
    const lockId = typeof lock === 'string' ? lock : lock.id
    await rpc('study.notes', { action: 'unlock_range', note_id: note.id, lock_id: lockId })
    if (selectedNote.value?.id === note.id) selectedNote.value = normalizeNote({ ...selectedNote.value, locks: selectedNote.value.locks.filter(item => item.id !== lockId) })
  }

  async function openNote(target: string): Promise<void> {
    if (!target.trim()) return
    const known = notes.value.find(note => note.id === target || note.path === target || note.title === target)
    await selectNote(known || normalizeNote({ id: target, path: target, title: target }))
  }

  onBeforeUnmount(() => {
    disposed = true
    ++listGeneration; ++treeGeneration; ++detailGeneration; ++graphGeneration
    clearTimeout(searchTimer)
  })

  return {
    notes, tree, selectedNote, graph,
    notesLoading, treeLoading, detailLoading, graphLoading, loadingMore,
    notesError, treeError, detailError, graphError, total, hasMore,
    recordError, loadNotes, loadTree, loadGraph, refreshNotes, searchNotes,
    selectNote, retryNoteDetail, saveNoteDocument, createNote, lockRange,
    unlockRange, openNote,
  }
}
