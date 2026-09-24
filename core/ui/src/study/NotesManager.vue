<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Braces, Code2, Eye, FilePlus2, GitBranch, ListTree, LockKeyhole, MessageSquare, Pencil, Quote, Save, Table2, UnlockKeyhole } from 'lucide-vue-next'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import { openContextMenu } from '../components/context-menu'
import { extractMarkdownHeadings } from './api'
import StudyNoteReferences from './StudyNoteReferences.vue'
import type { StudyMarkdownHeading } from './api'
import type { StudyNote, StudyNoteLock, StudyNoteTreeNode } from './types'
import type { NoteDocumentSaveMeta, NoteRange } from './useStudyNotes'

interface DraftState { content: string; revision: number; contentHash: string }
type DraftMap = Record<string, DraftState>

const props = withDefaults(defineProps<{
  notes: StudyNote[]
  selected: StudyNote | null
  tree?: StudyNoteTreeNode[]
  loading?: boolean
  detailLoading?: boolean
  active?: boolean
  error?: string
  detailError?: string
  onSelect: (note: StudyNote | null) => void | Promise<void>
  onRefresh?: () => void | Promise<void>
  onRetryDetail?: () => void | Promise<void>
  onSaveDocument?: (note: StudyNote, bodyMd: string, meta?: NoteDocumentSaveMeta) => void | StudyNote | null | Promise<void | StudyNote | null>
  onOpenNode?: (target: string) => void | Promise<void>
  onOpenNote?: (target: string) => void | Promise<void>
  onOpenChat?: () => void | Promise<void>
  onLockRange?: (note: StudyNote, range: NoteRange) => void | Promise<StudyNoteLock | null | void>
  onUnlockRange?: (note: StudyNote, lock: StudyNoteLock) => void | Promise<void>
  onCreate?: () => void | Promise<void>
}>(), {
  tree: () => [], loading: false, detailLoading: false, active: true, error: '', detailError: '',
  onRefresh: undefined, onRetryDetail: undefined, onSaveDocument: undefined, onOpenNode: undefined,
  onOpenNote: undefined, onOpenChat: undefined, onLockRange: undefined, onUnlockRange: undefined,
  onCreate: undefined,
})

const editMode = ref(false)
const drafts = ref<DraftMap>({})
const savedBodies = ref<Record<string, string>>({})
const saveState = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const saveError = ref('')
const lockError = ref('')
const lockOverlap = ref('')
const search = ref('')
const editor = ref<HTMLTextAreaElement | null>(null)
const preview = ref<HTMLElement | null>(null)
const outline = ref<StudyMarkdownHeading[]>([])
const viewScrollTop = ref(0)
const selectionSnapshot = ref<{ start: number; end: number } | null>(null)

const selectedId = computed(() => props.selected?.id || '')
const bodyMd = computed(() => {
  const note = props.selected
  if (!note) return ''
  return drafts.value[note.id]?.content ?? note.bodyMd
})
const originalBodyMd = computed(() => props.selected?.bodyMd || '')
const dirty = computed(() => Boolean(props.selected && bodyMd.value !== originalBodyMd.value && savedBodies.value[props.selected.id] !== bodyMd.value))
const hasRemoteNotes = computed(() => props.notes.length > 0)
const filteredNotes = computed(() => {
  const query = search.value.trim().toLocaleLowerCase()
  return query ? props.notes.filter(note => `${note.title} ${note.path}`.toLocaleLowerCase().includes(query)) : props.notes
})

function draftFor(note: StudyNote): DraftState | undefined { return drafts.value[note.id] }
function ensureDraft(note: StudyNote): DraftState {
  return draftFor(note) || { content: note.bodyMd, revision: note.revision, contentHash: note.contentHash }
}
function updateBody(value: string): void {
  const note = props.selected
  if (!note) return
  drafts.value = { ...drafts.value, [note.id]: { ...ensureDraft(note), content: value } }
  saveState.value = 'idle'; saveError.value = ''
}
function currentMeta(note: StudyNote): NoteDocumentSaveMeta {
  const draft = ensureDraft(note)
  return { revision: draft.revision || note.revision, contentHash: draft.contentHash || note.contentHash, resourceIds: note.resource_ids?.length ? note.resource_ids : note.resources.map(resource => resource.id).filter(Boolean) }
}
function noteForTarget(target: string): StudyNote | undefined {
  const folded = target.trim().toLocaleLowerCase()
  return props.notes.find(note => [note.id, note.path, note.title].some(value => String(value || '').toLocaleLowerCase() === folded))
}
function safeTarget(value: unknown): string {
  const target = String(value || '').trim()
  return /[\u0000-\u001f\u007f]/.test(target) ? '' : target
}
function wikilinkTarget(value: string): { target: string; label: string } {
  const [target, label] = value.split('|', 2)
  return { target: safeTarget(target), label: safeTarget(label || target) }
}
function resolveWikilink(target: string): { kind: 'note' | 'node' | 'unresolved'; target: string } {
  const typed = target.match(/^(note|node):(.*)$/i)
  if (typed) {
    const resolvedTarget = safeTarget(typed[2])
    return resolvedTarget ? { kind: typed[1].toLocaleLowerCase() as 'note' | 'node', target: resolvedTarget } : { kind: 'unresolved', target }
  }
  const folded = target.toLocaleLowerCase()
  const resolved = props.selected?.links.find(link =>
    String(link.target || '').toLocaleLowerCase() === folded
    || String(link.id || '').toLocaleLowerCase() === folded,
  )
  if (resolved?.kind === 'note' || resolved?.kind === 'node') {
    return { kind: resolved.kind, target: safeTarget(resolved.id || resolved.target) || target }
  }
  const note = noteForTarget(target)
  return note ? { kind: 'note', target: note.id } : { kind: 'unresolved', target }
}
function renderWikilinks(content: string): string {
  let fenced = false
  return content.split(/\r?\n/).map(line => {
    if (/^\s{0,3}(```+|~~~+)/.test(line)) { fenced = !fenced; return line }
    if (fenced || /^(?: {4}| {0,3}\t)/.test(line)) return line
    return line.split(/(`[^`]*`)/g).map((part, index) => {
      if (index % 2 === 1) return part
      return part.replace(/\[\[([^\]]+)\]\]/g, (_match, value: string) => {
        const link = wikilinkTarget(value)
        if (!link.target) return _match
        const resolved = resolveWikilink(link.target)
        return `[${link.label}](#study-${resolved.kind}=${encodeURIComponent(resolved.target)})`
      })
    }).join('')
  }).join('\n')
}
const renderedBody = computed(() => renderWikilinks(bodyMd.value))

type NoteNavigationAction = () => void | Promise<void>

/**
 * Every operation that can replace or hide the current document goes through
 * this gate.  StudyView also calls the exposed method for controls that live
 * outside this component (the file tree, workspace back button and header
 * chat action), so a dirty draft cannot be bypassed by changing chrome.
 */
async function requestNavigation(action: NoteNavigationAction): Promise<boolean> {
  const leavingNoteId = dirty.value ? props.selected?.id : undefined
  const leavingDraft = leavingNoteId ? drafts.value[leavingNoteId] : undefined
  if (dirty.value) {
    const confirmed = typeof window !== 'undefined' && typeof window.confirm === 'function'
      ? window.confirm('当前笔记有未保存修改，确定放弃修改并继续吗？')
      : false
    if (!confirmed) return false
  }
  await action()
  // A failed navigation must leave the draft intact. Do not discard edits
  // made while the destination was loading, or a newly selected note's draft.
  if (leavingNoteId && drafts.value[leavingNoteId] === leavingDraft) {
    const next = { ...drafts.value }; delete next[leavingNoteId]; drafts.value = next
    saveState.value = 'idle'; saveError.value = ''; lockError.value = ''
  }
  return true
}
function selectNote(note: StudyNote): void { void requestNavigation(() => props.onSelect(note)).catch(() => undefined) }

function toggleEdit(): void {
  selectionSnapshot.value = editor.value ? { start: editor.value.selectionStart, end: editor.value.selectionEnd } : null
  viewScrollTop.value = preview.value?.scrollTop || 0
  editMode.value = !editMode.value
  void nextTick(() => {
    if (editMode.value) {
      editor.value?.focus()
      if (selectionSnapshot.value) editor.value?.setSelectionRange(selectionSnapshot.value.start, selectionSnapshot.value.end)
    } else if (preview.value) preview.value.scrollTop = viewScrollTop.value
  })
}

function insertTemplate(kind: 'math' | 'code' | 'quote' | 'table' | 'mermaid' | 'callout'): void {
  const target = editor.value
  if (!target) return
  const templates: Record<typeof kind, string> = {
    math: '$$\nE = mc^2\n$$\n',
    code: '```python\n# 代码\n```\n',
    quote: '> 引用来源或关键论断\n',
    table: '| 项目 | 内容 |\n| --- | --- |\n| 结论 |  |\n',
    mermaid: '```mermaid\ngraph TD\n  A[起点] --> B[关系]\n```\n',
    callout: '> [!NOTE]\n> 需要回顾的要点\n',
  }
  const value = templates[kind]
  const start = target.selectionStart
  const end = target.selectionEnd
  updateBody(bodyMd.value.slice(0, start) + value + bodyMd.value.slice(end))
  void nextTick(() => { target.focus(); target.setSelectionRange(start + value.length, start + value.length) })
}

function saveErrorMessage(cause: unknown): string {
  const root = cause && typeof cause === 'object' ? cause as Record<string, unknown> : {}
  const data = root.data && typeof root.data === 'object' ? root.data as Record<string, unknown> : {}
  const code = String(root.code || data.code || data.error_code || data.error || '').trim()
  const rawReason = String(root.reason || data.reason || data.message || root.message || (cause instanceof Error ? cause.message : cause || '')).trim()
  const raw = code && rawReason ? `${code}: ${rawReason}` : code || rawReason
  if (/NOTE_REGION_LOCKED/i.test(raw)) {
    const structured = Object.keys(data).length ? data : root
    const overlap = structured?.overlap || structured?.overlap_quote || structured?.conflict_region || (Array.isArray(structured?.overlaps) ? structured.overlaps[0] : undefined)
    if (overlap && typeof overlap === 'object') {
      const range = overlap as Record<string, unknown>
      lockOverlap.value = `${String(range.quote || range.exact || '重合区域')}（${String(range.overlap_start ?? range.start ?? range.start_offset ?? '?')}–${String(range.overlap_end ?? range.end ?? range.end_offset ?? '?')}）`
    } else lockOverlap.value = typeof overlap === 'string' ? overlap : raw.match(/(?:overlap|重合)[^:：]*[:：]\s*([^;；]+)/i)?.[1]?.trim() || ''
    const reason = typeof structured?.reason === 'string' ? structured.reason : ''
    return `保存失败：${reason || 'Agent 锁定了这段内容'}。你的草稿仍保留，请核对重合区域。`
  }
  if (/REVISION_CONFLICT/i.test(raw)) return '保存失败：笔记已被更新，你的草稿仍保留。'
  return raw ? `保存失败：${raw}` : '保存失败，修改仍保留在当前编辑器。'
}
async function saveDocument(): Promise<void> {
  const note = props.selected
  if (!note || !dirty.value || saveState.value === 'saving') return
  if (!props.onSaveDocument) { saveState.value = 'error'; saveError.value = '当前笔记没有保存处理，修改仍保留。'; return }
  saveState.value = 'saving'; saveError.value = ''; lockError.value = ''
  try {
    const content = bodyMd.value
    const result = await props.onSaveDocument(note, content, currentMeta(note))
    const latest = result && result.id === note.id ? result : props.selected?.id === note.id ? props.selected : note
    // The draft remains in memory to preserve the editor contents, but its
    // CAS baseline must move to the server acknowledgement. Otherwise the
    // second consecutive save sends the first revision/hash and conflicts.
    drafts.value = {
      ...drafts.value,
      [note.id]: { content, revision: latest.revision, contentHash: latest.contentHash },
    }
    savedBodies.value = { ...savedBodies.value, [note.id]: content }
    saveState.value = 'saved'
  } catch (cause) { saveState.value = 'error'; saveError.value = saveErrorMessage(cause); lockError.value = saveError.value }
}
function discardChanges(): void {
  const note = props.selected
  if (!note) return
  const next = { ...drafts.value }; delete next[note.id]; drafts.value = next
  saveState.value = 'idle'; saveError.value = ''; lockError.value = ''
}

function rangeFromTextarea(): NoteRange | null {
  const note = props.selected
  const target = editor.value
  if (!note || !target || target.selectionStart === target.selectionEnd) return null
  const start = target.selectionStart
  const end = target.selectionEnd
  return { start, end, quote: bodyMd.value.slice(start, end), prefix: bodyMd.value.slice(Math.max(0, start - 40), start), suffix: bodyMd.value.slice(end, end + 40) }
}
function rangeFromPreview(): NoteRange | null {
  const note = props.selected
  const selection = window.getSelection()
  const root = preview.value
  if (!note || !selection || selection.isCollapsed || !root || !selection.toString().trim() || !root.contains(selection.anchorNode)) return null
  const quote = selection.toString()
  const first = bodyMd.value.indexOf(quote)
  if (first < 0) return null
  if (bodyMd.value.indexOf(quote, first + quote.length) >= 0) {
    lockError.value = '这段引用在文档中出现多次，无法安全锁定；请在编辑态框选。'
    return null
  }
  return { start: first, end: first + quote.length, quote }
}
async function lockSelection(range: NoteRange): Promise<void> {
  const note = props.selected
  if (!note || !props.onLockRange) return
  lockError.value = ''; lockOverlap.value = ''
  try { await props.onLockRange(note, range) }
  catch (cause) { lockError.value = saveErrorMessage(cause) }
}
function openLockMenu(event: MouseEvent, range: NoteRange | null): void {
  if (!range || !props.selected || !props.onLockRange) return
  event.preventDefault(); event.stopPropagation()
  openContextMenu({ event, ariaLabel: '笔记内容保护', items: [{ label: '锁定选中内容', icon: LockKeyhole, action: () => lockSelection(range) }] })
}
function handleEditorContextMenu(event: MouseEvent): void { openLockMenu(event, rangeFromTextarea()) }
function handlePreviewContextMenu(event: MouseEvent): void { openLockMenu(event, rangeFromPreview()) }
async function unlock(lock: StudyNoteLock): Promise<void> {
  if (!props.selected || !props.onUnlockRange) return
  try { await props.onUnlockRange(props.selected, lock) } catch (cause) { lockError.value = saveErrorMessage(cause) }
}

function handleDocumentClick(event: MouseEvent): void {
  const target = event.target as HTMLElement | null
  const anchor = target?.closest('a')
  const href = anchor?.getAttribute('href') || ''
  const match = href.match(/^#study-(note|node|unresolved)=(.*)$/)
  if (!anchor || !match) return
  event.preventDefault(); event.stopPropagation()
  let decoded = ''
  try { decoded = safeTarget(decodeURIComponent(match[2])) } catch { return }
  if (!decoded || match[1] === 'unresolved') { lockError.value = '未找到对应笔记，无法导航。'; return }
  if (match[1] === 'note') {
    const note = noteForTarget(decoded)
    void requestNavigation(() => note ? props.onSelect(note) : props.onOpenNote?.(decoded)).catch(() => undefined)
  } else void requestNavigation(() => props.onOpenNode?.(decoded)).catch(() => undefined)
}
function scrollHeading(heading: StudyMarkdownHeading): void {
  const target = preview.value?.querySelector<HTMLElement>(`[data-study-heading-id="${CSS.escape(heading.id)}"]`)
  target?.scrollIntoView?.({ behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
}
function syncOutline(): void {
  outline.value = extractMarkdownHeadings(bodyMd.value)
  if (!preview.value || editMode.value) return
  const headings = Array.from(preview.value.querySelectorAll<HTMLElement>('h1,h2,h3,h4,h5,h6'))
  const seen = new Map<string, number>()
  outline.value = headings.map((element, index) => {
    const text = element.textContent?.trim() || ''
    const base = text.toLocaleLowerCase().replace(/[^\w\u00a0-\uffff-]+/g, '-').replace(/^-+|-+$/g, '') || `heading-${index + 1}`
    const count = seen.get(base) || 0; seen.set(base, count + 1)
    const id = count ? `${base}-${count + 1}` : base
    element.dataset.studyHeadingId = id
    return { level: Number(element.tagName.slice(1)) as StudyMarkdownHeading['level'], text, id }
  }).filter(item => Boolean(item.text))
}
function handleKeydown(event: KeyboardEvent): void {
  if (!props.active || !editMode.value || !(event.metaKey || event.ctrlKey) || event.key.toLocaleLowerCase() !== 's') return
  event.preventDefault(); void saveDocument()
}
watch(bodyMd, syncOutline, { immediate: true })
watch(() => props.selected?.id, () => { editMode.value = false; saveState.value = 'idle'; saveError.value = ''; lockError.value = ''; void nextTick(syncOutline) })
onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))

defineExpose({ requestNavigation, isDirty: dirty })
</script>

<template>
  <section class="study-notes-manager" aria-label="Markdown 笔记工作区">
    <div v-if="error" class="study-notes-error" role="alert">{{ error }}</div>
    <header class="study-note-workspace-toolbar">
      <div class="study-note-workspace-actions">
        <button class="text-btn" type="button" :aria-pressed="editMode" @click="toggleEdit"><Pencil v-if="!editMode" :size="14" /><Eye v-else :size="14" />{{ editMode ? '预览' : '编辑' }}</button>
        <template v-if="editMode">
          <button class="text-btn" type="button" title="插入公式" @click="insertTemplate('math')"><Braces :size="14" />公式</button>
          <button class="text-btn" type="button" title="插入代码块" @click="insertTemplate('code')"><Code2 :size="14" />代码</button>
          <button class="text-btn" type="button" title="插入引用" @click="insertTemplate('quote')"><Quote :size="14" />引用</button>
          <button class="text-btn" type="button" title="插入表格" @click="insertTemplate('table')"><Table2 :size="14" />表格</button>
          <button class="text-btn" type="button" title="插入 Mermaid 图" @click="insertTemplate('mermaid')"><GitBranch :size="14" />Mermaid</button>
          <button class="text-btn" type="button" title="插入 Callout" @click="insertTemplate('callout')">Callout</button>
        </template>
      </div>
      <div class="study-note-workspace-actions">
        <span v-if="saveState === 'saving'" class="study-notes-muted" role="status">保存中…</span>
        <span v-else-if="saveState === 'saved'" class="study-note-save-success" role="status">已保存</span>
        <span v-else-if="dirty" class="study-notes-muted" role="status">未保存</span>
        <button v-if="dirty" class="text-btn" type="button" :disabled="saveState === 'saving'" @click="saveDocument"><Save :size="14" />保存</button>
        <button v-if="dirty" class="text-btn" type="button" :disabled="saveState === 'saving'" @click="discardChanges">放弃</button>
      </div>
    </header>
    <div v-if="detailLoading" class="study-note-detail-state" role="status">正在加载笔记…</div>
    <div v-else-if="detailError && !selected" class="study-note-detail-state" role="alert"><p>{{ detailError }}</p><button v-if="onRetryDetail" class="text-btn" type="button" @click="onRetryDetail">重试</button></div>
    <div v-else-if="!selected" class="study-note-empty-state">
      <FilePlus2 :size="18" aria-hidden="true" /><p>{{ hasRemoteNotes ? '从左侧文件树打开一篇笔记。' : '还没有 Markdown 笔记。' }}</p><button v-if="onCreate" class="text-btn" type="button" @click="onCreate">通过对话创建笔记</button>
    </div>
    <article v-else class="study-note-detail" :data-note-id="selected.id">
      <header class="study-note-detail-head"><div><h2>{{ selected.title }}</h2><p class="study-note-path">{{ selected.path || `${selected.title}.md` }}</p></div><button v-if="onOpenChat" class="text-btn" type="button" @click="onOpenChat"><MessageSquare :size="14" />对话</button></header>
      <div v-if="detailError" class="study-note-detail-error" role="status">{{ detailError }} <button v-if="onRetryDetail" class="text-btn" type="button" @click="onRetryDetail">重试</button></div>
      <div v-if="saveError || lockError" class="study-note-detail-error" role="alert">{{ saveError || lockError }}<span v-if="lockOverlap"> 重合区域：{{ lockOverlap }}</span></div>
      <div class="study-note-document-layout">
        <aside v-if="outline.length" class="study-note-outline" aria-label="文档大纲"><h3>大纲</h3><button v-for="heading in outline" :key="heading.id" class="study-note-outline-link" type="button" :style="{ paddingLeft: `calc(var(--space-2) + (var(--space-2) * ${heading.level - 1}))` }" @click="scrollHeading(heading)">{{ heading.text }}</button></aside>
        <main class="study-note-main">
          <div v-if="editMode" class="study-note-editor-shell" data-study-note-document><textarea ref="editor" class="study-note-full-editor" aria-label="编辑笔记全文" :value="bodyMd" spellcheck="true" @input="updateBody(($event.target as HTMLTextAreaElement).value)" @contextmenu="handleEditorContextMenu" /></div>
          <div v-else ref="preview" class="study-note-reading study-note-document" data-study-note-document @click="handleDocumentClick" @contextmenu="handlePreviewContextMenu"><MarkdownRenderer :content="renderedBody" :mermaid="true" /></div>
          <section v-if="selected.locks.length" class="study-note-locks" aria-label="已锁定区域"><h3><LockKeyhole :size="13" />Agent 保护区域</h3><ul><li v-for="lock in selected.locks" :key="lock.id"><span class="study-note-lock-quote">{{ lock.quote || `${lock.start}–${lock.end}` }}</span><button v-if="onUnlockRange" class="text-btn" type="button" :aria-label="`解锁 ${lock.quote || lock.id}`" @click="unlock(lock)"><UnlockKeyhole :size="13" />解锁</button></li></ul></section>
          <StudyNoteReferences :resources="selected.resources" />
        </main>
      </div>
    </article>
  </section>
</template>
