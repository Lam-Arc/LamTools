<template>
  <div ref="root" class="inline-file-composer" @pointerdown="focusEmptyEditor" @contextmenu="$emit('contextmenu', $event)">
    <CommandPalette v-if="completionItems.length && !dismissed" :commands="completionItems" :active-index="activeIndex" @select="selectCompletion" />
    <div ref="editorHost" />

  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EditorState, Compartment, Prec } from '@codemirror/state'
import { EditorView, Decoration, WidgetType, ViewPlugin, keymap, placeholder as editorPlaceholder, type DecorationSet } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { activeCompletion, referenceSpans } from '@/composer/fileReferences'
import type { CoreAttachment, CoreCommandCatalogItem } from '@/types'
import CommandPalette from './CommandPalette.vue'
import { useReferenceActions } from '@/helpers/referenceActions'

export interface ComposerEditorHandle {
  value: string; selectionStart: number; selectionEnd: number; selectionDirection: 'forward' | 'backward' | 'none'
  focus(options?: FocusOptions): void; setSelectionRange(start: number, end: number, direction?: string): void
  select(): void; resize(): void; hasFocus(): boolean
}
const props = withDefaults(defineProps<{
  modelValue: string; placeholder?: string; disabled?: boolean; attachments?: CoreAttachment[]
  suggestions?: { name: string; path: string; description?: string; context?: boolean }[]
}>(), { attachments: () => [], suggestions: () => [] })
const emit = defineEmits<{
  'update:modelValue': [text: string]; input: []; click: []; keyup: [event: KeyboardEvent]; keydown: [event: KeyboardEvent]
  paste: [event: ClipboardEvent]; contextmenu: [event: MouseEvent]; 'preview-file': [path: string]; 'reveal-file': [path: string]
  'request-suggestions': [trigger: string, query: string]; 'reference-file': [path: string]; 'retry-file': [path: string]
}>()
const root = ref<HTMLElement>(), editorHost = ref<HTMLElement>()
const referenceActions = useReferenceActions()
const caret = ref(0), activeIndex = ref(0), dismissed = ref(false)
const completion = computed(() => activeCompletion(props.modelValue, caret.value))
const completionItems = computed<CoreCommandCatalogItem[]>(() => {
  if (!completion.value || completion.value.trigger === '/') return []
  const query = completion.value.query.toLowerCase()
  return props.suggestions.filter(s => Boolean(s.context) === (completion.value!.trigger === '#'))
    .filter(s => `${s.name} ${s.path}`.toLowerCase().includes(query)).slice(0, 12)
    .map(s => ({ name: s.name, title: s.name, description: s.description || s.path, icon: '@', source: 'core', action: 'insert_token', kind: 'skill', metadata: { reference_path: s.path, context: s.context } }))
})
let view: EditorView | undefined
// user:“无法输入文字，会点到‘给sunday发送任务’这个提示”+(提示是不可编辑的装饰；空白处和提示的点击统一交给真实编辑区，避免缩窄后选中提示文字)。
function focusEmptyEditor(event: PointerEvent) {
  if (props.disabled || props.modelValue || event.button > 0 || !(event.target instanceof Element)) return
  if (event.target.closest('button, .command-palette, .composer-file-token')) return
  event.preventDefault()
  view?.focus()
}
let consumedEnter = false
const disabledConfig = new Compartment()
const placeholderConfig = new Compartment()

// user:“输入框内自动渲染成这样”+(完整路径留在编辑文档中，原子装饰只显示图标和文件名)。
class FileWidget extends WidgetType {
  constructor(readonly path: string, readonly name: string, readonly status: string) { super() }
  eq(other: FileWidget) { return this.path === other.path && this.status === other.status }
  toDOM() {
    const span = document.createElement('span')
    span.className = 'composer-file-token'
    span.dataset.filePath = this.path
    span.title = this.path.startsWith('pending://') ? `${this.name} · ${this.status === 'failed' ? '处理失败，可移除后重新添加' : '正在处理'}` : `${this.name}\n${this.path}`
    span.setAttribute('aria-label', span.title)
    span.textContent = `${this.status === 'uploading' ? '◌' : this.status === 'failed' ? '⚠' : /\.(png|jpe?g|webp|gif|bmp)$/i.test(this.name) ? '▧' : '▤'} @${this.name}`
    span.dataset.status = this.status
    if (this.status === 'uploading') span.setAttribute('aria-busy', 'true')
    span.addEventListener('mousedown', e => { e.preventDefault(); if (this.status === 'failed') emit('retry-file', this.path); else if (!this.path.startsWith('pending://')) emit('preview-file', this.path) })
    span.addEventListener('contextmenu', e => { e.preventDefault(); e.stopPropagation(); referenceActions.menu(e, this.path) })
    return span
  }
  ignoreEvent() { return true }
}
function decorations(editor: EditorView): DecorationSet {
  return Decoration.set(referenceSpans(editor.state.doc.toString()).map(span => {
    const attachment = props.attachments.find(a => a.path === span.path || a.path?.replace(/\\/g, '/') === span.path)
    const status = attachment?.status || (span.path.startsWith('pending://') ? 'failed' : 'uploaded')
    return Decoration.replace({ widget: new FileWidget(span.path, attachment?.filename || span.name, status) }).range(span.from, span.to)
  }))
}
function selectCompletion(command: CoreCommandCatalogItem) {
  const range = completion.value
  if (!range || !view) return
  const path = String(command.metadata?.reference_path || '')
  const insert = command.metadata?.context ? `#${command.name} ${path} ` : '@' + JSON.stringify(path.replace(/\\/g, '/')) + ' '
  view.dispatch({ changes: { from: range.from, to: range.to, insert }, selection: { anchor: range.from + insert.length } })
  dismissed.value = true
  if (!command.metadata?.context) emit('reference-file', path)
  view.focus()
}
watch(completion, value => {
  dismissed.value = false; activeIndex.value = 0
  if (value && value.trigger !== '/') emit('request-suggestions', value.trigger, value.query)
})
watch(() => props.modelValue, text => {
  if (!view || view.state.doc.toString() === text) return
  const previous = view.state.doc.toString()
  let from = 0, suffix = 0
  while (from < previous.length && from < text.length && previous[from] === text[from]) from++
  while (suffix < previous.length - from && suffix < text.length - from && previous[previous.length - suffix - 1] === text[text.length - suffix - 1]) suffix++
  view.dispatch({ changes: { from, to: previous.length - suffix, insert: text.slice(from, text.length - suffix) } })
})
watch(() => props.disabled, value => view?.dispatch({ effects: disabledConfig.reconfigure([EditorView.editable.of(!value), EditorState.readOnly.of(Boolean(value))]) }))
watch(() => props.placeholder, value => view?.dispatch({ effects: placeholderConfig.reconfigure(editorPlaceholder(value || '输入内容，/ 命令 · @ 文件 · # 上下文')) }))
watch(() => props.attachments, () => view?.dispatch({}), { deep: true })
onMounted(() => {
  const files = ViewPlugin.fromClass(class {
    decorations: DecorationSet
    constructor(editor: EditorView) { this.decorations = decorations(editor) }
    update(update: { view: EditorView }) { this.decorations = decorations(update.view) }
  }, { decorations: value => value.decorations, provide: plugin => EditorView.atomicRanges.of(editor => editor.plugin(plugin)?.decorations || Decoration.none) })
  view = new EditorView({ parent: editorHost.value, state: EditorState.create({ doc: props.modelValue, extensions: [
    history(), keymap.of([...defaultKeymap, ...historyKeymap]), EditorView.lineWrapping, files,
    disabledConfig.of([EditorView.editable.of(!props.disabled), EditorState.readOnly.of(Boolean(props.disabled))]), placeholderConfig.of(editorPlaceholder(props.placeholder || '输入内容，/ 命令 · @ 文件 · # 上下文')),
    EditorView.contentAttributes.of({ role: 'textbox', 'aria-multiline': 'true', 'aria-label': '消息输入框' }),
    EditorView.updateListener.of(update => {
      caret.value = update.state.selection.main.head
      if (update.docChanged) { emit('update:modelValue', update.state.doc.toString()); emit('input') }
      if (update.selectionSet) emit('click')
    }),
    Prec.high(EditorView.domEventHandlers({
      keydown(event) {
        if (event.isComposing || view?.composing) return false
        if (completionItems.value.length && !dismissed.value) {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); activeIndex.value = (activeIndex.value + (event.key === 'ArrowDown' ? 1 : -1) + completionItems.value.length) % completionItems.value.length; return true }
          if (event.key === 'Escape') { event.preventDefault(); dismissed.value = true; return true }
          if (event.key === 'Enter' || event.key === 'Tab') { event.preventDefault(); consumedEnter = event.key === 'Enter'; selectCompletion(completionItems.value[activeIndex.value]!); return true }
        }
        emit('keydown', event)
        return event.defaultPrevented
      },
      keyup(event) { if (event.key === 'Enter' && consumedEnter) { consumedEnter = false; event.preventDefault(); return true } if (!event.isComposing) emit('keyup', event); return event.defaultPrevented },
      paste(event) { emit('paste', event); return event.defaultPrevented },
    })),
    EditorView.theme({ '&': { color: 'var(--theme-composer-text)', backgroundColor: 'transparent' }, '&.cm-focused': { outline: 'none' }, '.cm-content': { padding: '8px 0', fontFamily: 'var(--font-sans)', minHeight: '38px', caretColor: 'var(--theme-composer-text)' }, '.cm-scroller': { maxHeight: '160px', overflow: 'auto', fontFamily: 'inherit', lineHeight: '1.6' }, '.cm-line': { padding: '0' }, '.cm-placeholder': { color: 'color-mix(in srgb,var(--theme-composer-text) 45%,transparent)' } }),
  ] }) })
})
onBeforeUnmount(() => view?.destroy())
defineExpose({
  get value() { return view?.state.doc.toString() || props.modelValue },
  get selectionStart() { return view?.state.selection.main.from || 0 },
  get selectionEnd() { return view?.state.selection.main.to || 0 },
  get selectionDirection() { return 'none' as const },
  focus(_options?: FocusOptions) { view?.focus() },
  setSelectionRange(start: number, end: number) { if (view) view.dispatch({ selection: { anchor: Math.min(start, view.state.doc.length), head: Math.min(end, view.state.doc.length) } }) },
  select() { if (view) view.dispatch({ selection: { anchor: 0, head: view.state.doc.length } }) },
  resize() {}, hasFocus() { return view?.hasFocus || false },
})
</script>

<style scoped>
/* user:“范围不对，光标出格了”+(共享编辑器本身提供输入留白，让提示、选区和光标在主区与分屏中都避开卡片圆角)。 */
.inline-file-composer { position: relative; box-sizing: border-box; width: 100%; min-width: 0; padding: var(--space-1) var(--space-4) 0; --text: var(--theme-composer-text); }
:deep(.cm-placeholder) { pointer-events: none; user-select: none; }
:deep(.composer-file-token) { display: inline-block; border-radius: var(--radius-sm); padding: 0 var(--space-1); background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: color-mix(in srgb, var(--text) 85%, transparent); font: inherit; cursor: pointer; }
:deep(.composer-file-token:hover) { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); }
:deep(.composer-file-token[data-status=failed]) { color: var(--red); }
</style>
