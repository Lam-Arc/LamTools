<script setup lang="ts">
import { computed, defineAsyncComponent, markRaw, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import type { Node, ViewportTransform } from '@vue-flow/core'
import { ArrowLeft, ChevronRight } from 'lucide-vue-next'
import { useCorePluginModeContext, usePluginModeRuntime } from '../plugins/context'
import HistoryLoadingIndicator from '../components/HistoryLoadingIndicator.vue'
import StudySidebarHost from './StudySidebarHost.vue'
import MarksPanel from './MarksPanel.vue'
import NotesManager from './NotesManager.vue'
import StudyNoteRelationGraph from './StudyNoteRelationGraph.vue'
import type { Course, KnowledgeItem, Net, Relation, SessionBinding, StudyNoteTreeNode, StudyPin, StudySubject } from './types'
import { normalizeKnowledgeItem, normalizeNet, normalizeSessionBinding, subjectParams } from './api'
import type { StudyRpc } from './api'
import { useStudyNotes } from './useStudyNotes'
import { stableLayeredStudyLayout, STUDY_LAYOUT_LIMITS, type StudyLayoutPosition } from './layout'
import { selectionEvents } from './annotations'
import './study.css'

const StudyGraph = defineAsyncComponent(() => import('./StudyGraph.vue'))

const props = withDefaults(defineProps<{ pluginId?: string; modeId?: string }>(), { pluginId: 'study', modeId: 'study' })
const ctx = useCorePluginModeContext()
const chat = ctx.chat
const rpc = ctx.requestRpc as StudyRpc
type StudyPage = 'chat' | 'map' | 'notes' | string

const page = ref<StudyPage>('chat')
const courses = ref<Course[]>([])
const net = ref<Net>({ revision: 0, total: 0 })
const path = ref<KnowledgeItem[]>([])
const nodes = shallowRef<Node[]>([])
const viewport = ref<ViewportTransform>({ x: 24, y: 24, zoom: 1 })
const error = ref('')
const ready = ref(false)
const initializing = ref(false)
const preSessionLoading = ref(false)
const loading = ref(false)
const selected = ref<KnowledgeItem | null>(null)
const currentBinding = ref<SessionBinding | null>(null)
const mapBinding = ref<SessionBinding | null>(null)
const returnSource = ref<{ page: StudyPage; path: KnowledgeItem[]; sessionId: string | null }>({ page: 'chat', path: [], sessionId: null })
const inspected = ref<{ node: KnowledgeItem; neighbors: KnowledgeItem[]; relations: Relation[] } | null>(null)
const graphFocusId = ref('')
const graphSelectedId = ref('')
const { notes, tree: noteTree, selectedNote, graph: noteGraph, notesLoading, treeLoading: notesTreeLoading, treeError: notesTreeError, detailLoading: notesDetailLoading, graphLoading: notesGraphLoading, graphError: notesGraphError, notesError, detailError: notesDetailError,
  recordError, loadTree: loadNoteTree, refreshNotes, selectNote, retryNoteDetail, saveNoteDocument, lockRange, unlockRange, openNote } = useStudyNotes(rpc)
const notesVisited = ref(false)
const notesReturnPending = ref(false)
type NotesManagerNavigationApi = {
  requestNavigation: (action: () => void | Promise<void>) => Promise<boolean>
}
const notesManager = ref<NotesManagerNavigationApi | null>(null)
const noteWorkspaceActive = computed(() => page.value === 'notes' || currentBinding.value?.subject.kind === 'notes')
/**
 * The Note vault is a host capability rather than a UI preference.  A host
 * that declares no `notes` capability never offers the workspace, so the user
 * cannot reach controls the host cannot serve.
 */
const notesEnabled = computed(() => {
  const capabilities = ctx.modeCapabilities
  return !capabilities || capabilities.includes('notes')
})
const rightRailInitializedForNotes = ref(false)
const pins = ref<StudyPin[]>([])
const pinCacheKey = ref('')
const layoutNotice = ref('')
const drafts = new Map<string, string>()
const prefilledSessions = new Set<string>()
let inspectGeneration = 0
let sessionSelectionGeneration = 0
let initializeGeneration = 0
let pinsGeneration = 0
let generation = 0
let disposed = false
let refreshTimer: ReturnType<typeof setTimeout> | undefined
let draftTimer: ReturnType<typeof setTimeout> | undefined
let mapBindingPromise: Promise<SessionBinding | null> | null = null
const offset = ref(0)

const inGraph = computed(() => !['chat', 'notes'].includes(page.value))
const isMapManagementChat = computed(() => {
  if (page.value !== 'chat' || selected.value) return false
  const currentSubject = currentBinding.value?.subject
  if (currentSubject?.kind === 'map' && currentSubject.id === 'map') return true
  return Boolean(mapBinding.value?.sessionId && ctx.activeSessionId.value === mapBinding.value.sessionId)
})
const sidebarActive = computed(() => {
  if (page.value === 'map') return 'map'
  if (page.value === 'notes' || (page.value === 'chat' && currentBinding.value?.subject.kind === 'notes')) return 'notes'
  return isMapManagementChat.value ? 'manage' : ''
})
const graphScope = computed(() => `${page.value}:${path.value.at(-1)?.id || ''}:${offset.value}`)
function report(cause: unknown): void { error.value = cause instanceof Error ? cause.message : String(cause) }
function isGroup(item: KnowledgeItem): boolean { return item.entity === 'course' || !item.learnable }
function statusFor(item: KnowledgeItem): { label: string; icon: 'check' | 'circle' } {
  if (item.progressRole === 'aggregate' && item.assessment === 'unassessed') return { label: '范围进度，尚未独立评估', icon: 'circle' }
  if (item.assessment === 'pass') return { label: `已通过，掌握${item.mastery === 'low' ? '低' : item.mastery === 'medium' ? '中' : item.mastery === 'high' ? '高' : '待评定'}`, icon: 'check' }
  if (item.assessment === 'fail') return { label: '已评估但未通过', icon: 'circle' }
  return { label: '尚未评估', icon: 'circle' }
}

async function ensureBinding(subject: StudySubject, replacePrimary = false): Promise<SessionBinding | null> {
  const payload = { ...subjectParams(subject), replace_primary: replacePrimary }
  const result = await rpc('study.session', payload)
  return normalizeSessionBinding(result, subject)
}

async function ensureMapBinding(): Promise<SessionBinding | null> {
  if (mapBinding.value) return mapBinding.value
  if (!mapBindingPromise) {
    mapBindingPromise = ensureBinding({ kind: 'map', id: 'map' })
      .then(binding => {
        if (binding) mapBinding.value = binding
        return binding
      })
      .finally(() => { mapBindingPromise = null })
  }
  return mapBindingPromise
}

function saveDraftForSession(sessionId: string | null): void {
  if (!sessionId) return
  drafts.set(sessionId, ctx.composerText.value)
  clearTimeout(draftTimer)
  draftTimer = setTimeout(() => { draftTimer = undefined }, 250)
}

function prefillWasIssued(sessionId: string): boolean {
  if (prefilledSessions.has(sessionId)) return true
  try {
    if (localStorage.getItem(`lamtools-study-prefill:${sessionId}`) === '1') {
      prefilledSessions.add(sessionId)
      return true
    }
  } catch { /* storage is optional */ }
  return false
}

function rememberPrefill(sessionId: string): void {
  prefilledSessions.add(sessionId)
  try { localStorage.setItem(`lamtools-study-prefill:${sessionId}`, '1') } catch { /* storage is optional */ }
}

function restoreDraft(binding: SessionBinding, node: KnowledgeItem | null): void {
  const previous = drafts.get(binding.sessionId)
  const serverDraft = typeof binding.draft === 'string' ? binding.draft : undefined
  if (typeof serverDraft === 'string') drafts.set(binding.sessionId, serverDraft)
  const draft = serverDraft ?? previous
  if (draft !== undefined) {
    ctx.composerText.value = draft
    return
  }
  if (node && !prefillWasIssued(binding.sessionId)) {
    rememberPrefill(binding.sessionId)
    ctx.composerText.value = `我想学${node.name}，给我讲一下`
  } else {
    ctx.composerText.value = ''
  }
}

function sessionIsKnown(sessionId: string): boolean {
  return ctx.sessions.value.some(session => session.id === sessionId)
}

async function activateBinding(binding: SessionBinding, node: KnowledgeItem | null = null, forceSelect = false): Promise<void> {
  // A binding can point at a just-created session that is not in the shared
  // list yet. Refresh only for that missing session; existing bindings do not
  // need a full list round-trip before switching.
  if (!sessionIsKnown(binding.sessionId)) await ctx.refreshSessions()
  if (disposed) return
  if (forceSelect || ctx.activeSessionId.value !== binding.sessionId) {
    await ctx.selectSession(binding.sessionId)
  }
  if (disposed) return
  currentBinding.value = binding
  restoreDraft(binding, node)
  ready.value = true
}

async function selectBinding(subject: StudySubject, node: KnowledgeItem | null = null): Promise<SessionBinding | null> {
  saveDraftForSession(currentBinding.value?.sessionId || ctx.activeSessionId.value)
  const binding = await ensureBinding(subject)
  if (!binding) return null
  await activateBinding(binding, node)
  return binding
}

async function latestStudyContext(): Promise<{ context?: Record<string, unknown>; text: string; instructions?: string }> {
  const fallback: Record<string, unknown> = { session_id: currentBinding.value?.sessionId || ctx.activeSessionId.value || '', ...(selected.value ? { selected_node_id: selected.value.id } : {}) }
  const result = await rpc('study.context', {
    session_id: currentBinding.value?.sessionId || ctx.activeSessionId.value || '',
    ...(selected.value ? { node_id: selected.value.id } : {}),
  })
  const context = isRecord(result.latest_context) ? result.latest_context : isRecord(result.context) ? result.context : fallback
  const rawText = typeof result.request_local_late_context === 'string' ? result.request_local_late_context : JSON.stringify(context)
  return {
    context,
    text: rawText.length <= 20_000 ? rawText : JSON.stringify(fallback),
    instructions: typeof result.instructions === 'string' && result.instructions.trim() ? result.instructions : undefined,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> { return Boolean(value) && typeof value === 'object' && !Array.isArray(value) }

async function turnOptions(): Promise<Record<string, unknown>> {
  const dynamic = await latestStudyContext()
  return {
    active_mode: 'study:study',
    request_local_late_context: dynamic.text,
    ...(dynamic.instructions ? { instructions: dynamic.instructions } : {}),
    ...(dynamic.context ? { study_context: dynamic.context } : {}),
    ...(selected.value ? { study_node_id: selected.value.id } : {}),
    ...(selectedNote.value ? {
      study_note_id: selectedNote.value.id,
      study_note_path: selectedNote.value.path,
      study_note_revision: selectedNote.value.revision,
    } : {}),
    study_session_id: currentBinding.value?.sessionId || ctx.activeSessionId.value || '',
    work_root: '',
  }
}

async function openSearch(): Promise<void> {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('lamtools:open-search', { detail: { scope: 'study' } }))
}

function scopeCacheKey(scope: unknown): string {
  if (!isRecord(scope)) return ''
  const user = String(scope.user_id || scope.authenticated_user_id || '').trim()
  const environment = String(scope.environment_id || scope.env_id || '').trim()
  const library = String(scope.library_id || '').trim()
  if (!user || !environment || !library) return ''
  return `lamtools-study-pins:${encodeURIComponent([user, environment, library].join('\u001f'))}`
}

function normalizePins(value: unknown): StudyPin[] {
  if (!Array.isArray(value)) return []
  return value.filter(item => isRecord(item)).map(item => ({
    id: String(item.id || item.entity_id || ''),
    kind: String(item.kind || item.entity_type || '') as StudyPin['kind'],
    title: String(item.title || item.id || item.entity_id || ''),
  })).filter(item => Boolean(item.id) && (item.kind === 'node' || item.kind === 'note' || item.kind === 'session'))
}

function mirrorPins(): void {
  if (!pinCacheKey.value || typeof localStorage === 'undefined') return
  try { localStorage.setItem(pinCacheKey.value, JSON.stringify(pins.value)) } catch { /* cache is optional */ }
}

async function loadPins(): Promise<void> {
  const token = ++pinsGeneration
  try {
    const result = await rpc('study.pin', { action: 'list' })
    if (disposed || token !== pinsGeneration) return
    pins.value = normalizePins(result.pins)
    pinCacheKey.value = scopeCacheKey(result.scope)
    mirrorPins()
  } catch (cause) {
    if (disposed || token !== pinsGeneration) return
    // The server is authoritative; an unavailable endpoint must not revive an
    // unscoped local pin list or make another Study scope visible.
    pins.value = []
    report(cause)
  }
}

async function togglePin(pin: StudyPin): Promise<void> {
  const exists = pins.value.some(candidate => candidate.kind === pin.kind && candidate.id === pin.id)
  try {
    const result = await rpc('study.pin', {
      action: exists ? 'remove' : 'add', entity_type: pin.kind, entity_id: pin.id,
    })
    pins.value = normalizePins(result.pins)
    pinCacheKey.value = scopeCacheKey(result.scope) || pinCacheKey.value
    mirrorPins()
  } catch (cause) { report(cause) }
}

async function loadChildren(parent: { id: string; kind: 'course' | 'module'; courseId?: string }): Promise<KnowledgeItem[]> {
  const courseId = parent.kind === 'course' ? parent.id : parent.courseId
  if (!courseId) return []
  const result = await rpc('study.get', parent.kind === 'course'
    ? { course_id: courseId, limit: 50 }
    : { course_id: courseId, module_id: parent.id, limit: 50 })
  const parsed = normalizeNet(result)
  const rows = parsed.items?.length ? parsed.items : (parsed.neighbors || [])
  return rows.map(item => ({ ...item, entity: item.entity || 'node' }))
}

async function requestOverview(): Promise<Net> {
  const result = normalizeNet(await rpc('study.get', { view: 'overview', limit: 50 }))
  return result
}

async function overview(): Promise<Net> {
  const result = await requestOverview()
  courses.value = result.courses || []
  return result
}

async function openStudyNodeTarget(target: string): Promise<void> {
  try {
    const folded = target.trim().toLocaleLowerCase()
    if (!folded) return
    const existing = nodes.value.find(node => {
      const item = node.data as KnowledgeItem | undefined
      return node.id.toLocaleLowerCase() === folded || item?.id?.toLocaleLowerCase() === folded || item?.name?.toLocaleLowerCase() === folded
    })
    if (existing) {
      const item = existing.data as KnowledgeItem
      await openNode(item)
      return
    }
    const result = normalizeNet(await rpc('study.get', { node_id: target }))
    if (result.node) await openNode(result.node)
  } catch (cause) { recordError(cause) }
}

function ensureNotesRightPanel(): void {
  if (rightRailInitializedForNotes.value) return
  rightRailInitializedForNotes.value = true
  ctx.ensureRightPanelOpen?.()
}

/**
 * NotesManager owns the draft and is the single navigation gate.  Keep the
 * action itself inside the gate so a cancelled confirmation cannot partially
 * change the page, active session, or selected document.
 */
async function requestNoteNavigation(action: () => void | Promise<void>): Promise<boolean> {
  const manager = notesManager.value
  if (!manager) {
    await action()
    return true
  }
  return manager.requestNavigation(action)
}

async function leaveNotes(): Promise<void> {
  try {
    await requestNoteNavigation(async () => {
      await saveLayout()
      const binding = await ensureMapBinding()
      if (!binding) throw new Error('无法打开学习会话，请重试')
      saveDraftForSession(currentBinding.value?.sessionId || ctx.activeSessionId.value)
      // Commit the page change only after the learning session is available.
      // A notes binding would otherwise keep the file tree active in chat.
      await activateBinding(binding, null, true)
      if (disposed) return
      selected.value = null
      page.value = 'chat'
      notesReturnPending.value = false
    })
  } catch (cause) { report(cause) }
}

async function selectNoteFromTree(node: StudyNoteTreeNode): Promise<void> {
  const target = String(node.noteId || node.note_id || node.id || node.path || '').trim()
  if (!target || node.kind === 'folder') return
  await requestNoteNavigation(async () => {
    page.value = 'notes'
    notesVisited.value = true
    ensureNotesRightPanel()
    await openNote(target)
  })
}

async function openNoteFromGraph(target: string): Promise<void> {
  await requestNoteNavigation(async () => {
    page.value = 'notes'
    notesVisited.value = true
    ensureNotesRightPanel()
    await openNote(target)
  })
}

async function openNotesChat(): Promise<void> {
  await requestNoteNavigation(async () => {
    notesReturnPending.value = true
    const binding = await selectBinding({ kind: 'notes', id: 'notes' })
    if (!binding || disposed) return
    page.value = 'chat'
    ready.value = true
  })
}

const unregister = usePluginModeRuntime().register(`${props.pluginId}:${props.modeId}`, {
  // Keep the plugin surface mounted for the first binding so it can show the
  // shared history loader. Later Study switches stay on Core's thread surface
  // and use its canonical loader without remounting the message tree.
  useCoreThread: computed(() => page.value === 'chat' && ready.value && !error.value),
  composerPlaceholder: computed(() => currentBinding.value?.subject.kind === 'notes' ? '想如何整理笔记…' : '想学什么…'),
  composerDisabled: computed(() => !ready.value || chat.activeTurnRunning.value),
  allowAttachmentOnlySubmit: true,
  hideComposer: computed(() => page.value !== 'chat'),
  turnOptions,
  sidebar: {
    groups: [],
    component: markRaw(StudySidebarHost),
    componentProps: computed(() => ({
      courses: courses.value,
      active: sidebarActive.value,
      select: navigate,
      loadChildren,
      openNode,
      openPin: openPinned,
      openSearch,
      pins: pins.value,
      togglePin,
      noteWorkspaceActive: noteWorkspaceActive.value,
      noteTree: noteTree.value,
      activeNoteId: selectedNote.value?.id || '',
      noteTreeLoading: notesTreeLoading.value,
      noteTreeError: notesTreeError.value,
      selectNote: selectNoteFromTree,
      refreshNoteTree: loadNoteTree,
      leaveNotes,
      notesEnabled: notesEnabled.value,
    })),
    primaryActionLabel: '',
    onPrimaryAction: () => navigate('chat'),
    allowProjectNewSession: false,
  },
  rightSidebar: computed(() => noteWorkspaceActive.value || currentBinding.value?.subject.kind === 'notes'
    ? [{
        id: 'study-note-graph',
        title: '笔记关系图',
        component: markRaw(StudyNoteRelationGraph),
        componentProps: {
          graph: noteGraph.value,
          activeId: selectedNote.value?.id || '',
          loading: notesGraphLoading.value,
          error: notesGraphError.value,
          onOpenNote: openNoteFromGraph,
        },
      }]
    : [{ id: 'study-marks', title: '标记', component: markRaw(MarksPanel) }]),
})

function setGraphViewport(next: ViewportTransform): void { viewport.value = { ...next } }
async function syncGraphViewport(next: ViewportTransform): Promise<void> { viewport.value = { ...next }; await saveLayout() }

async function saveNavigation(): Promise<void> {
  if (!inGraph.value) return
  const state = { page: page.value, path: path.value, offset: offset.value }
  await rpc('study.layout', { scope: 'navigation', value: state })
}

async function saveLayout(): Promise<void> {
  if (!inGraph.value || loading.value) return
  await rpc('study.layout', { scope: graphScope.value, value: { viewport: viewport.value, positions: Object.fromEntries(nodes.value.map(node => [node.id, node.position])) } })
  await saveNavigation()
}

async function inspectNode(item: KnowledgeItem): Promise<void> {
  const token = ++inspectGeneration
  inspected.value = null
  if (isGroup(item)) return
  try {
    const result = normalizeNet(await rpc('study.get', { node_id: item.id, limit: 12 }))
    if (token === inspectGeneration && !disposed) inspected.value = { node: result.node || item, neighbors: result.neighbors || [], relations: result.relations || [] }
  } catch (cause) { if (token === inspectGeneration) report(cause) }
}

function focusGraphNode(item: KnowledgeItem): void { graphFocusId.value = item.id; void inspectNode(item) }
function blurGraphNode(item: KnowledgeItem): void { if (graphFocusId.value === item.id) graphFocusId.value = '' }
async function loadGraph(restore = true): Promise<void> {
  const token = ++generation
  loading.value = true
  inspected.value = null
  inspectGeneration++
  layoutNotice.value = ''
  try {
    const params = page.value === 'map'
      ? { view: 'overview', limit: 50, include: ['summary', 'status'] }
      : {
          course_id: page.value,
          module_id: path.value.at(-1)?.id,
          offset: offset.value,
          limit: 50,
          ...(offset.value > 0
            ? { expected_structure_revision: net.value.structureRevision ?? net.value.structure_revision ?? net.value.revision }
            : {}),
        }
    const [rawResult, layoutResponse] = await Promise.all([
      rpc('study.get', params),
      restore ? rpc('study.layout', { scope: graphScope.value }) : Promise.resolve(null),
    ])
    const result = normalizeNet(rawResult)
    if (disposed || token !== generation) return
    net.value = result
    const stored = isRecord(layoutResponse?.value) ? layoutResponse.value as { viewport?: ViewportTransform; positions?: Record<string, StudyLayoutPosition> } : undefined
    if (stored?.viewport) setGraphViewport(stored.viewport)
    else if (restore) setGraphViewport({ x: 24, y: 24, zoom: 1 })
    const graphItems = page.value === 'map'
      ? (result.courses || []).map(course => ({ ...course, entity: 'course' }))
      : (result.items || [])
    const items = graphItems.map(item => {
      const normalized = normalizeKnowledgeItem(item, item.entity === 'module' || item.entity === 'course' ? item.entity : 'node')
      // `normalizeKnowledgeItem` intentionally models node `passed` as a
      // boolean. Keep the overview aggregate's numeric count alongside it so
      // the course sphere can render passed / total without changing the
      // stable node contract.
      return item.entity === 'course' ? { ...normalized, progressPassed: Number(item.passed) } : normalized
    })
    if (items.length > STUDY_LAYOUT_LIMITS.maxInteractiveNodes || (result.relations || []).length > STUDY_LAYOUT_LIMITS.maxInteractiveEdges) layoutNotice.value = `局部图超过建议范围（${STUDY_LAYOUT_LIMITS.maxInteractiveNodes} 节点 / ${STUDY_LAYOUT_LIMITS.maxInteractiveEdges} 条关系），已保持分页；当前布局在主线程分层计算。`
    const previous = Object.fromEntries(nodes.value.map(node => [node.id, node.position])) as Record<string, StudyLayoutPosition>
    const preserved: Record<string, StudyLayoutPosition> = {}
    items.forEach(item => {
      const position = stored?.positions?.[item.id] || (!restore ? previous[item.id] : undefined)
      if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) preserved[item.id] = position
    })
    const positions = stableLayeredStudyLayout(items, result.relations || [], preserved)
    nodes.value = items.map(item => ({
      id: item.id,
      type: 'knowledge',
      class: `study-graph-node study-graph-node--${item.entity === 'course' ? 'course' : isGroup(item) ? 'module' : 'knowledge'}`,
      data: item,
      position: positions[item.id] || { x: 0, y: 0 },
    }))
    if (!items.some(item => item.id === graphSelectedId.value)) graphSelectedId.value = ''
    if (!items.some(item => item.id === graphFocusId.value)) graphFocusId.value = ''
  } catch (cause) { if (token === generation) report(cause) }
  finally { if (token === generation) loading.value = false }
}

async function navigate(id: string): Promise<void> {
  try {
    await saveLayout()
    if (id === 'manage') {
      saveDraftForSession(currentBinding.value?.sessionId || ctx.activeSessionId.value)
      selected.value = null
      page.value = 'chat'
      preSessionLoading.value = true
      const binding = await ensureMapBinding()
      if (binding) {
        mapBinding.value = binding
        await activateBinding(binding, null, true)
      }
      ready.value = Boolean(binding)
      preSessionLoading.value = false
      return
    }
    if (id === 'chat') {
      page.value = 'chat'
      preSessionLoading.value = true
      const binding = selected.value ? await selectBinding({ kind: 'node', id: selected.value.id }, selected.value) : await ensureMapBinding()
      if (binding && !selected.value) await activateBinding(binding, null)
      ready.value = true
      preSessionLoading.value = false
      return
    }
    if (id === 'notes') {
      if (!notesEnabled.value) return
      page.value = 'notes'; notesVisited.value = true; selected.value = null; notesReturnPending.value = false; ensureNotesRightPanel()
      await Promise.all([refreshNotes(), selectBinding({ kind: 'notes', id: 'notes' })]); return
    }
    page.value = id; path.value = []; offset.value = 0
    if (inGraph.value) await loadGraph()
  } catch (cause) { preSessionLoading.value = false; report(cause) }
}

async function openNode(item: KnowledgeItem): Promise<void> {
  try {
    graphSelectedId.value = item.id
    await saveLayout()
    if (item.entity === 'course') {
      page.value = item.id; path.value = []; offset.value = 0; await loadGraph(); await saveNavigation(); return
    }
    if (isGroup(item)) {
      path.value = [...path.value, item]; offset.value = 0; await loadGraph(); await saveNavigation(); return
    }
    selected.value = item
    returnSource.value = { page: page.value, path: [...path.value], sessionId: currentBinding.value?.sessionId || ctx.activeSessionId.value }
    page.value = 'chat'
    await selectBinding({ kind: 'node', id: item.id }, item)
  } catch (cause) { report(cause) }
}

async function openPinned(pin: StudyPin): Promise<void> {
  if (pin.kind === 'session') {
    await ctx.selectSession(pin.id)
    page.value = 'chat'
    return
  }
  if (pin.kind === 'note') {
    await requestNoteNavigation(async () => {
      page.value = 'notes'; notesVisited.value = true
      ensureNotesRightPanel()
      await openNote(pin.id)
    })
    return
  }
  const result = normalizeNet(await rpc('study.get', { node_id: pin.id }))
  if (result.node) await openNode(result.node)
}

async function back(): Promise<void> {
  if (page.value === 'notes') {
    await requestNoteNavigation(async () => {
      await saveLayout()
      if (returnSource.value.page === 'chat') {
        page.value = 'chat'
        if (returnSource.value.sessionId) await ctx.selectSession(returnSource.value.sessionId)
      } else {
        page.value = returnSource.value.page; path.value = [...returnSource.value.path]; await loadGraph()
      }
    })
    return
  }
  try {
    await saveLayout()
    if (page.value === 'chat' && notesReturnPending.value) {
      page.value = 'notes'
      notesReturnPending.value = false
      ensureNotesRightPanel()
      return
    }
    if (returnSource.value.page === 'chat') {
      page.value = 'chat'
      if (returnSource.value.sessionId) await ctx.selectSession(returnSource.value.sessionId)
    } else {
      page.value = returnSource.value.page; path.value = [...returnSource.value.path]; await loadGraph()
    }
  } catch (cause) { report(cause) }
}

async function collapse(depth: number): Promise<void> {
  path.value = path.value.slice(0, depth); offset.value = 0; await loadGraph(); await saveNavigation()
}

async function resumeGraph(): Promise<void> {
  returnSource.value = { page: page.value, path: [...path.value], sessionId: currentBinding.value?.sessionId || ctx.activeSessionId.value }
  page.value = 'map'; path.value = []; offset.value = 0; await loadGraph()
}

async function handleStudySearchHit(event: Event): Promise<void> {
  const detail = (event as CustomEvent<Record<string, unknown>>).detail || {}
  const entityType = String(detail.entity_type || detail.entityType || '')
  const entityId = String(detail.entity_id || detail.node_id || detail.note_id || detail.id || '')
  if (!entityId) return
  try {
    if (entityType === 'note' || detail.note_id) {
      await requestNoteNavigation(async () => {
        page.value = 'notes'; notesVisited.value = true
        ensureNotesRightPanel()
        await openNote(entityId)
      })
      return
    }
    if (entityType === 'session' && detail.session_id) {
      await ctx.selectSession(String(detail.session_id))
      page.value = 'chat'
      return
    }
    const result = normalizeNet(await rpc('study.get', { node_id: entityId }))
    const node = result.node || (result.current?.id === entityId ? result.current : null)
    if (node) await openNode(node)
  } catch (cause) { report(cause) }
}

async function refresh(): Promise<void> {
  if (loading.value || disposed) return
  if (page.value === 'notes') { await refreshNotes(); return }
  try {
    const result = await overview()
    if (result.revision !== net.value.revision && inGraph.value) await loadGraph(false)
  } catch (cause) { report(cause) }
}

watch(ctx.composerText, () => saveDraftForSession(currentBinding.value?.sessionId || ctx.activeSessionId.value))
watch(ctx.lastEvent, event => {
  if (event?.method !== 'study/changed') return
  if (!refreshTimer) refreshTimer = setTimeout(() => { refreshTimer = undefined; void refresh() }, 120)
})
watch([ctx.activeSessionId, ctx.sessions], async ([sessionId]) => {
  const token = ++sessionSelectionGeneration
  const session = ctx.sessions.value.find(item => item.id === sessionId)
  if (session?.metadata?.owner_plugin !== 'study') return
  const nodeId = typeof session.metadata.study_node_id === 'string' ? session.metadata.study_node_id : ''
  if (!nodeId) { if (sessionId !== currentBinding.value?.sessionId) selected.value = null; return }
  try {
    const result = normalizeNet(await rpc('study.get', { node_id: nodeId }))
    if (!disposed && token === sessionSelectionGeneration) selected.value = result.node || null
  } catch (cause) { if (token === sessionSelectionGeneration) report(cause) }
}, { immediate: true })

async function initialize(): Promise<void> {
  if (initializing.value || disposed) return
  const token = ++initializeGeneration
  initializing.value = true; error.value = ''
  preSessionLoading.value = true
  try {
    const [binding, initialNet] = await Promise.all([
      ensureMapBinding(),
      requestOverview(),
    ])
    if (disposed || token !== initializeGeneration) return
    mapBinding.value = binding
    if (binding) await activateBinding(binding, null, true)
    if (disposed || token !== initializeGeneration) return
    ready.value = true
    net.value = initialNet
    courses.value = initialNet.courses || []
  } catch (cause) {
    if (token === initializeGeneration && !disposed) report(cause)
  } finally {
    if (token === initializeGeneration) {
      preSessionLoading.value = false
      initializing.value = false
    }
  }
}

function handleStudyChat(): void { page.value = 'chat' }
onMounted(() => {
  void loadPins()
  selectionEvents.addEventListener('study-chat', handleStudyChat)
  window.addEventListener('lamtools:study-search-hit', handleStudySearchHit)
  void initialize()
})
onBeforeUnmount(() => {
  void saveLayout().catch(report)
  disposed = true; generation++; initializeGeneration++; pinsGeneration++; clearTimeout(refreshTimer); clearTimeout(draftTimer)
  selectionEvents.removeEventListener('study-chat', handleStudyChat)
  window.removeEventListener('lamtools:study-search-hit', handleStudySearchHit)
  unregister()
})
</script>

<template>
  <section class="study-view" aria-label="Study">
    <p v-if="error" class="study-error" role="alert">{{ error }} <button class="text-btn" :disabled="initializing" @click="ready ? (inGraph ? loadGraph() : initialize()) : initialize()">重试</button></p>
    <HistoryLoadingIndicator v-if="page === 'chat'" :active="preSessionLoading" />
    <div v-if="page === 'chat'" data-study-core-thread-host aria-hidden="true"></div>
    <NotesManager
      v-if="notesVisited"
      ref="notesManager"
      v-show="page === 'notes'"
      :active="page === 'notes'"
      :notes="notes"
      :selected="selectedNote"
      :tree="noteTree"
      :loading="notesLoading"
      :detail-loading="notesDetailLoading"
      :error="notesError"
      :detail-error="notesDetailError"
      :on-select="selectNote"
      :on-refresh="refreshNotes"
      :on-retry-detail="retryNoteDetail"
      :on-save-document="saveNoteDocument"
      :on-open-node="openStudyNodeTarget"
      :on-open-note="openNote"
      :on-open-chat="openNotesChat"
      :on-lock-range="lockRange"
      :on-unlock-range="unlockRange"
      :on-create="openNotesChat"
    />
    <div v-if="inGraph" class="study-graph">
      <StudyGraph
        v-model:nodes="nodes"
        :net="net"
        :viewport="viewport"
        :loading="loading"
        :graph-focus-id="graphFocusId"
        :graph-selected-id="graphSelectedId"
        :inspected="inspected"
        :layout-notice="layoutNotice"
        @update:viewport="setGraphViewport"
        @open-node="openNode"
        @focus-node="focusGraphNode"
        @blur-node="blurGraphNode"
        @save-layout="saveLayout().catch(report)"
        @sync-viewport="syncGraphViewport($event).catch(report)"
        @report="report"
      />
      <footer v-if="net.total > 50" class="study-toolbar"><button class="text-btn" :disabled="offset === 0" @click="saveLayout().then(() => { offset -= 50; return loadGraph() }).catch(report)">上页</button><span>{{ offset + 1 }}–{{ Math.min(offset + 50, net.total) }} / {{ net.total }}</span><button class="text-btn" :disabled="offset + 50 >= net.total" @click="saveLayout().then(() => { offset += 50; return loadGraph() }).catch(report)">下页</button></footer>
    </div>
  </section>
  <Teleport defer to=".workspace-plugin-header">
    <header class="study-toolbar study-header" data-study-header>
      <button v-if="page !== 'chat' || notesReturnPending" class="text-btn" @click="back"><ArrowLeft :size="16" />返回</button>
      <button v-else class="text-btn" @click="resumeGraph">知识图谱</button>
      <h1 class="study-header-title">{{ page === 'chat' ? (selected?.name || (currentBinding?.subject.kind === 'notes' ? '笔记助手' : '学习')) : page === 'notes' ? (selectedNote?.title || '笔记') : (path.at(-1)?.name || net.course?.name || '图谱') }}</h1>
      <button v-if="page === 'notes'" class="text-btn study-note-header-chat" type="button" @click="openNotesChat">对话</button>
      <span v-if="page === 'notes' && selectedNote" class="study-note-header-path">{{ selectedNote.path }}</span>
      <nav v-if="inGraph" class="study-breadcrumbs" aria-label="知识层级"><button class="text-btn" @click="collapse(0)">{{ net.course?.name || '图谱' }}</button><template v-for="(item, index) in path" :key="item.id"><ChevronRight :size="12" /><button class="text-btn" @click="collapse(index + 1)">{{ item.name }}</button></template></nav>
      <span v-if="loading" class="study-header-loading" role="status">加载中…</span>
    </header>
  </Teleport>
</template>
