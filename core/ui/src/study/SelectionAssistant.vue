<script setup lang="ts">
import { computed, h, nextTick, onBeforeUnmount, onMounted, ref, render, watch } from 'vue'
import { Bookmark, Copy, Languages, Lightbulb, MessageCircle, Send, X } from 'lucide-vue-next'
import { useCorePluginModeContext } from '../plugins/context'
import { openContextMenu } from '../components/context-menu'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import { captureAnchor, anchorRange, splitRangeForFormulaHighlight } from './anchors'
import { normalizeMark } from './api'
import { marks, selectionEvents } from './annotations'
import type { MarkAnchor, StudyMark, TextAction } from './types'
import './study.css'

const props = defineProps<{ sessionId: string | null; mode: string; themeMode: string; jump: (anchor: MarkAnchor) => Promise<void> }>()
const ctx = useCorePluginModeContext()
const selected = ref<StudyMark | null>(null)
type DisplayAction = Exclude<TextAction, 'mark'>
const action = ref<DisplayAction>('explain')
const question = ref('')
const error = ref('')
const busy = ref(false)
const hover = ref(false)
const x = ref(24), y = ref(80)
const card = ref<HTMLElement>()
let observer: MutationObserver | undefined
let timer: ReturnType<typeof setTimeout> | undefined
let hoverTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let decorating = false
let requestGeneration = 0
let pendingRequest: { token: number; id: string; requestId: string } | null = null
const ranges = new Map<string, Range>()
const decorations = new Map<string, HTMLSpanElement>()
const content = computed(() => selected.value?.[action.value === 'ask' ? 'explain' : action.value] || '')
const titles: Record<DisplayAction, string> = { explain: '解释', translate: '翻译', ask: '询问' }

function updateMark(mark: StudyMark) {
  const index = marks.value.findIndex(m => m.id === mark.id)
  if (index < 0) marks.value = [...marks.value, mark]
  else marks.value = marks.value.map(m => m.id === mark.id ? mark : m)
  if (selected.value?.id === mark.id) selected.value = mark
  schedule()
}
function report(e: unknown) { error.value = e instanceof Error ? e.message : String(e) }
function position(px: number, py: number) {
  x.value = Math.max(8, Math.min(px, window.innerWidth - Math.min(360, window.innerWidth - 16) - 8))
  y.value = Math.max(8, Math.min(py, window.innerHeight - Math.min(440, window.innerHeight - 16) - 8))
}
function open(mark: StudyMark, kind: DisplayAction, px = window.innerWidth - 390, py = 80, preview = false) {
  requestGeneration++
  selected.value = mark; action.value = kind; hover.value = preview; question.value = ''; error.value = ''; busy.value = false
  position(px, py)
}
async function invoke() {
  if (!selected.value || busy.value) return
  const token = ++requestGeneration, id = selected.value.id, kind = action.value
  const requestId = globalThis.crypto?.randomUUID?.() || `study-text-${Date.now()}-${token}`
  pendingRequest = { token, id, requestId }
  busy.value = true; error.value = ''; hover.value = false
  try {
    const result = await (ctx.requestDirectRpc || ctx.requestRpc)('study.text', { id, action: kind, question: question.value, model_id: ctx.selectedModelId.value, request_id: requestId })
    if (token !== requestGeneration || selected.value?.id !== id || pendingRequest?.requestId !== requestId) return
    updateMark(normalizeMark(result.mark))
    question.value = ''
  } catch (e) { if (token === requestGeneration && selected.value?.id === id) report(e) }
  finally {
    if (token === requestGeneration && pendingRequest?.requestId === requestId) { busy.value = false; pendingRequest = null }
  }
}
async function create(anchor: MarkAnchor, kind: DisplayAction, event: MouseEvent) {
  try {
    const result = await ctx.requestRpc('study.marks', { action: 'create', anchor })
    const mark = normalizeMark(result.mark)
    updateMark(mark); open(mark, kind, event.clientX, event.clientY)
    if (kind !== 'ask' && !mark[kind]) await invoke()
    else if (kind === 'ask') { await nextTick(); card.value?.querySelector('textarea')?.focus() }
  } catch (e) { ctx.setRuntimeStatus(e instanceof Error ? e.message : String(e), 5000) }
}
async function createPureMark(anchor: MarkAnchor): Promise<void> {
  try {
    const result = await ctx.requestRpc('study.marks', { action: 'create', anchor, pure: true })
    updateMark(normalizeMark(result.mark))
  } catch (e) { ctx.setRuntimeStatus(e instanceof Error ? e.message : String(e), 5000) }
}
function menu(event: MouseEvent) {
  // A note document owns its own context menu (lock/unlock). The global mark
  // assistant must never turn a Markdown editing selection into a study mark.
  if ((event.target as Element | null)?.closest?.('[data-study-note-document]')) return
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || !selection.toString().trim()) return
  if (!(event.target instanceof Node) || !(selection.containsNode(event.target, true) || event.target.contains(selection.anchorNode))) return
  const anchor = captureAnchor(selection, props.sessionId || '', props.mode)
  if (!anchor) return
  const copiedText = selection.toString()
  event.stopImmediatePropagation()
  openContextMenu({ event, ariaLabel: '选文', items: [
    { label: '复制', icon: Copy, action: () => navigator.clipboard.writeText(copiedText) },
    { type: 'separator' },
    { label: '标记', icon: Bookmark, action: () => createPureMark(anchor) },
    { label: '解释', icon: Lightbulb, action: () => create(anchor, 'explain', event) },
    { label: '询问', icon: MessageCircle, action: () => create(anchor, 'ask', event) },
    { label: '翻译', icon: Languages, action: () => create(anchor, 'translate', event) },
  ] })
}
function clearDecorations() {
  const parents = new Set<Node>()
  for (const icon of decorations.values()) {
    if (icon.parentNode) parents.add(icon.parentNode)
    render(null, icon)
    icon.remove()
  }
  decorations.clear()
  for (const parent of parents) parent.normalize()
}
function insertDecoration(mark: StudyMark, range: Range) {
  const icon = document.createElement('span')
  icon.className = `study-mark-icon study-mark-icon--${props.themeMode === 'dark' ? 'dark' : 'light'}`
  icon.dataset.studyMarkIcon = mark.id
  icon.setAttribute('role', 'img')
  icon.setAttribute('aria-label', '已标记')
  render(h(Bookmark, { size: 13, strokeWidth: 2.25, 'aria-hidden': 'true' }), icon)

  const startElement = range.startContainer instanceof Element ? range.startContainer : range.startContainer.parentElement
  const katex = startElement?.closest('.katex')
  const formula = katex?.closest('.katex-display') || katex
  if (formula?.parentNode) formula.parentNode.insertBefore(icon, formula)
  else {
    const insertion = range.cloneRange()
    insertion.collapse(true)
    insertion.insertNode(icon)
  }
  decorations.set(mark.id, icon)
}
function restore() {
  decorating = true
  clearDecorations()
  ranges.clear()
  for (const mark of marks.value) {
    if (mark.anchor.session_id && mark.anchor.session_id !== props.sessionId) continue
    if (mark.anchor.document_id.startsWith('view:') && !mark.anchor.document_id.startsWith(`view:${props.mode}:`)) continue
    const range = anchorRange(mark.anchor)
    const startElement = range?.startContainer instanceof Element ? range.startContainer : range?.startContainer.parentElement
    if (startElement?.closest('[data-study-note-document]')) continue
    if (range) {
      ranges.set(mark.id, range)
      insertDecoration(mark, range)
    }
  }
  const api = CSS as unknown as { highlights?: Map<string, unknown> }
  const HighlightType = (window as unknown as { Highlight?: new (...ranges: Range[]) => unknown }).Highlight
  if (api.highlights && HighlightType) {
    const textRanges: Range[] = []
    const formulaRanges: Range[] = []
    for (const range of ranges.values()) {
      const split = splitRangeForFormulaHighlight(range)
      textRanges.push(...split.textRanges)
      formulaRanges.push(...split.formulaRanges)
    }
    const theme = props.themeMode === 'dark' ? 'dark' : 'light'
    for (const name of ['study-marks', 'study-marks-text', 'study-marks-formula', 'study-marks-text-light', 'study-marks-formula-light', 'study-marks-text-dark', 'study-marks-formula-dark']) api.highlights.delete(name)
    api.highlights.set(`study-marks-text-${theme}`, new HighlightType(...textRanges))
    api.highlights.set(`study-marks-formula-${theme}`, new HighlightType(...formulaRanges))
  }
  queueMicrotask(() => { decorating = false })
}
function schedule() { if (!timer) timer = setTimeout(() => { timer = undefined; if (!disposed) restore() }, 180) }
function hit(event: MouseEvent): StudyMark | undefined {
  for (const [id, range] of ranges) {
    if (Array.from(range.getClientRects()).some(r => event.clientX >= r.left && event.clientX <= r.right && event.clientY >= r.top && event.clientY <= r.bottom)) return marks.value.find(m => m.id === id)
  }
}
function click(event: MouseEvent) {
  if ((event.target as Element)?.closest('.selection-card,[data-context-menu-panel],.study-mark-icon')) return
  if (window.getSelection()?.toString().trim()) return
  const mark = hit(event)
  if (mark) open(mark, mark.thread.length ? 'ask' : mark.explain ? 'explain' : 'translate', event.clientX, event.clientY)
  else close()
}
function move(event: MouseEvent) {
  clearTimeout(hoverTimer)
  if ((event.target as Element)?.closest('.selection-card') || selected.value && !hover.value) return
  const mark = hit(event)
  if (!mark) { if (hover.value) hoverTimer = setTimeout(close, 250); return }
  if (!mark.explain && !mark.translate) return
  hoverTimer = setTimeout(() => open(mark, mark.translate ? 'translate' : 'explain', event.clientX, event.clientY + 12, true), 350)
}
function close() {
  requestGeneration++
  if (pendingRequest) {
    void ctx.requestRpc('study.text.cancel', { request_id: pendingRequest.requestId, id: pendingRequest.id }).catch(() => undefined)
    pendingRequest = null
  }
  selected.value = null; busy.value = false; clearTimeout(hoverTimer)
}
function key(event: KeyboardEvent) { if (event.key === 'Escape') close() }
function resize() {
  const viewport = window.visualViewport
  position(x.value + (viewport?.offsetLeft || 0), y.value + (viewport?.offsetTop || 0))
}
function keepOpen() { clearTimeout(hoverTimer) }
async function loadMarks() {
  try {
    const all: StudyMark[] = []
    let offset = 0
    let cursor: string | null = null
    for (let page = 0; page < 100; page += 1) {
      const result = await ctx.requestRpc('study.marks', { action: 'list', limit: 100, ...(cursor ? { cursor } : { offset }) })
      const rows = Array.isArray(result.marks) ? result.marks.map(normalizeMark) : []
      all.push(...rows)
      const next = typeof result.next_cursor === 'string' ? result.next_cursor : typeof result.nextCursor === 'string' ? result.nextCursor : null
      const hasMore = result.has_more === true || result.hasMore === true || Boolean(next) || all.length < Number(result.total || all.length)
      if (!hasMore || !rows.length) break
      if (next) cursor = next
      else offset += rows.length
    }
    if (!disposed) { marks.value = all; schedule() }
  } catch { /* Plugin may be disabled; actions still report their own error. */ }
}
function handleOpen(event: Event) {
  const detail = (event as CustomEvent<{ mark: StudyMark; action: TextAction }>).detail
  if (detail.action !== 'mark') open(detail.mark, detail.action)
}
async function handleJump(event: Event) {
  const mark = (event as CustomEvent<StudyMark>).detail
  try {
    close()
    await props.jump(mark.anchor)
    await nextTick()
    const range = anchorRange(mark.anchor)
    if (!range) throw new Error('原文已变化或暂未加载，无法准确定位。')
    const el = range.startContainer.parentElement
    el?.scrollIntoView({ block: 'center' })
    schedule()
  } catch (e) { ctx.setRuntimeStatus(e instanceof Error ? e.message : String(e), 5000) }
}
async function handleDelete(event: Event) {
  const mark = (event as CustomEvent<StudyMark>).detail
  try { await ctx.requestRpc('study.marks', { action: 'delete', id: mark.id }); marks.value = marks.value.filter(m => m.id !== mark.id); if (selected.value?.id === mark.id) close(); schedule() }
  catch (e) { ctx.setRuntimeStatus(e instanceof Error ? e.message : String(e), 5000) }
}
watch(() => [props.sessionId, props.mode, props.themeMode], () => { close(); schedule() })
watch(ctx.lastEvent, (event) => { if (event?.method === 'study/changed' && ['study.marks', 'study.text'].includes(String(event.payload.operation))) void loadMarks() })
onMounted(() => {
  void loadMarks()
  document.addEventListener('contextmenu', menu, true)
  document.addEventListener('click', click)
  document.addEventListener('mousemove', move, { passive: true })
  document.addEventListener('pointermove', move as EventListener, { passive: true })
  document.addEventListener('keydown', key)
  window.addEventListener('resize', resize)
  window.visualViewport?.addEventListener('resize', resize)
  window.visualViewport?.addEventListener('scroll', resize)
  selectionEvents.addEventListener('open', handleOpen)
  selectionEvents.addEventListener('jump', handleJump)
  selectionEvents.addEventListener('delete', handleDelete)
  observer = new MutationObserver(records => { if (!decorating && marks.value.length && records.some(r => !(r.target instanceof Element ? r.target : r.target.parentElement)?.closest('.selection-card,[data-context-menu-panel],.study-mark-icon'))) schedule() })
  observer.observe(document.body, { subtree: true, childList: true, characterData: true })
})
onBeforeUnmount(() => {
  disposed = true; observer?.disconnect(); clearTimeout(timer); clearTimeout(hoverTimer)
  document.removeEventListener('contextmenu', menu, true); document.removeEventListener('click', click); document.removeEventListener('mousemove', move); document.removeEventListener('pointermove', move as EventListener); document.removeEventListener('keydown', key); window.removeEventListener('resize', resize)
  window.visualViewport?.removeEventListener('resize', resize)
  window.visualViewport?.removeEventListener('scroll', resize)
  selectionEvents.removeEventListener('open', handleOpen); selectionEvents.removeEventListener('jump', handleJump); selectionEvents.removeEventListener('delete', handleDelete)
  const highlights = (CSS as unknown as { highlights?: Map<string, unknown> }).highlights
  highlights?.delete('study-marks')
  highlights?.delete('study-marks-text')
  highlights?.delete('study-marks-formula')
  highlights?.delete('study-marks-text-light')
  highlights?.delete('study-marks-formula-light')
  highlights?.delete('study-marks-text-dark')
  highlights?.delete('study-marks-formula-dark')
  clearDecorations()
})
</script>
<template>
  <Teleport to="body">
    <section v-if="selected" ref="card" class="selection-card optical-glass"
      :style="{ left: x + 'px', top: y + 'px' }" role="dialog" :aria-label="titles[action]" @mouseenter="keepOpen" @pointerdown="hover = false">
      <header>
        <button v-for="(title, kind) in titles" :key="kind" class="text-btn" :aria-pressed="action === kind" :disabled="busy" @click="action = kind; hover = false; error = ''">{{ title }}</button>
        <button class="text-btn selection-close" aria-label="关闭" @click="close"><X :size="15" /></button>
      </header>
      <blockquote>{{ selected.anchor.quote }}</blockquote>
      <div class="selection-answer" aria-live="polite">
        <template v-if="action === 'ask'">
          <template v-for="(turn, i) in selected.thread" :key="i">
            <p v-if="turn.role === 'user'" class="selection-question">{{ turn.content }}</p>
            <MarkdownRenderer v-else class="selection-assistant-markdown" :content="turn.content" :mermaid="false" />
          </template>
          <p v-if="!selected.thread.length">想了解什么？</p>
        </template>
        <template v-else-if="action === 'translate' && selected.dictionary">
          <strong>{{ selected.dictionary.word }}</strong> <span>{{ selected.dictionary.phonetic }}</span>
          <p><em>{{ selected.dictionary.pos }}</em> {{ selected.dictionary.zh }}</p><p>{{ selected.dictionary.en }}</p><p v-if="selected.dictionary.example">{{ selected.dictionary.example }}</p>
        </template>
        <MarkdownRenderer v-else-if="content" class="selection-assistant-markdown" :content="content" :mermaid="false" />
        <button v-else-if="!busy" class="text-btn" @click="invoke">{{ titles[action] }}</button>
        <p v-if="busy" role="status">正在回答…</p><p v-if="error" class="study-error" role="alert">{{ error }}</p>
      </div>
      <form v-if="action === 'ask'" @submit.prevent="invoke">
        <textarea v-model="question" aria-label="问题" placeholder="继续问…" rows="2" maxlength="4000" :disabled="busy" @keydown.ctrl.enter.prevent="invoke" />
        <button class="text-btn" aria-label="发送" :disabled="busy || !question.trim()"><Send :size="16" /></button>
      </form>
    </section>
  </Teleport>
</template>
<style>
::highlight(study-marks-text-light) {
  color: var(--study-mark-light);
  background: transparent;
  text-decoration: none;
}
::highlight(study-marks-formula-light) {
  color: var(--study-mark-light);
  background: transparent;
  text-decoration: none;
}
::highlight(study-marks-text-dark) {
  color: var(--study-mark-dark);
  background: transparent;
  text-decoration: none;
}
::highlight(study-marks-formula-dark) {
  color: var(--study-mark-dark);
  background: transparent;
  text-decoration: none;
}
.study-mark-icon--light { --study-mark-color: var(--study-mark-light); }
.study-mark-icon--dark { --study-mark-color: var(--study-mark-dark); }
.study-mark-icon { display: inline-grid; place-items: center; width: 15px; height: 15px; margin-inline-end: 3px; vertical-align: -.16em; color: var(--study-mark-color); pointer-events: none; }
.selection-card { --text: var(--theme-main-text); position: fixed; z-index: var(--z-popover); width: min(360px, calc(100vw - 24px)); max-height: min(60dvh, 440px); display: flex; flex-direction: column; overflow: hidden; border-radius: var(--radius); color: var(--text); padding: var(--space-3); font-size: 13px; line-height: 1.35; }
.selection-card header, .selection-card form { display: flex; gap: var(--space-1); align-items: center; }
.selection-card .selection-close { margin-left: auto; }
.selection-card button[aria-pressed=true] { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-active), transparent); color: var(--theme-main-text); }
.selection-card blockquote { margin: var(--space-2) 0; padding: 0; max-height: 56px; overflow: auto; font-size: 12px; opacity: .8; white-space: pre-wrap; overflow-wrap: anywhere; }
.selection-answer { min-height: 32px; overflow: auto; flex: 1; white-space: pre-wrap; overflow-wrap: anywhere; }
.selection-answer p { margin: 0 0 var(--space-2); }
.selection-answer .selection-question { font-weight: 650; }
.selection-answer .markdown-body { white-space: normal; line-height: 1.35; }
.selection-answer .markdown-body :is(p, ul, ol) { margin-block: var(--space-1); }
.selection-answer .markdown-body :is(p, ul, ol):first-child { margin-block-start: 0; }
.selection-answer .markdown-body :is(p, ul, ol):last-child { margin-block-end: 0; }
.selection-answer .markdown-body :is(h1, h2, h3, h4) { margin: var(--space-2) 0 var(--space-1); line-height: 1.2; }
.selection-answer .markdown-body :is(h1, h2, h3, h4):first-child { margin-top: 0; }
.selection-answer .markdown-body :is(ul, ol) { padding-left: var(--space-4); }
.selection-answer .markdown-body li { margin: 0; }
.selection-card form { margin-top: var(--space-2); }
.selection-card textarea { flex: 1; width: 100%; min-width: 0; resize: none; max-height: 7.25em; overflow: auto; border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent); border-radius: var(--radius-sm); padding: var(--space-2); background: var(--theme-composer-soft-background); color: var(--theme-composer-text); font: inherit; line-height: 1.45; outline: none; }
.selection-card button:disabled { opacity: .45; }
</style>
