<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EditorState } from '@codemirror/state'
import { EditorView, drawSelection, highlightActiveLine, keymap, lineNumbers } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { defaultHighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { javascript } from '@codemirror/lang-javascript'
import { markdown } from '@codemirror/lang-markdown'
import { json } from '@codemirror/lang-json'
import { RefreshCw, Save } from 'lucide-vue-next'
import CoreConfirmDialog from './CoreConfirmDialog.vue'
import type { SplitTab } from '@/split/layout'
import type { SplitWorkspaceController } from '@/split/useSplitWorkspace'
import type { createSplitDocuments } from '@/split/documents'
const props = defineProps<{ tab: SplitTab; root: string; controller: SplitWorkspaceController; documents: ReturnType<typeof createSplitDocuments>; visible?: boolean }>()
const emit = defineEmits<{ dirty: [id: string, value: boolean] }>()
const view = props.documents.get(props.root, props.tab.resource, props.tab.id), { doc, dirty } = view
const host = ref<HTMLElement | null>(null), savePath = ref(props.tab.resource), pending = ref<(() => void) | null>(null)
let editor: EditorView | undefined, editorText = ''
let measureFrame = 0, resizeObserver: ResizeObserver | undefined
// user:“内容不见了 要向下滚动很长很长才能看见内容”+(分屏标签在隐藏或零尺寸时挂载会让
// CodeMirror 保留错误视口；重新可见时主动测量一次，必要时重读未被编辑的文件)。
function measure() {
  if (typeof requestAnimationFrame === 'undefined') { editor?.requestMeasure(); return }
  cancelAnimationFrame(measureFrame)
  measureFrame = requestAnimationFrame(() => { editor?.requestMeasure() })
}
function reload() {
  if (doc.loading || doc.saving || dirty.value) return
  void view.load().then(measure)
}
const unregister = props.controller.registerGuard(props.tab.id, proceed => { if (dirty.value || doc.saving) pending.value = proceed; else proceed() })
watch(dirty, value => emit('dirty', props.tab.id, value), { immediate: true })
// user:“审查分屏代码，并优化”+(自己输入的内容不再每键比较整篇文档；只有另一视图或磁盘真的改了内容才回写编辑器)。
watch(() => doc.content, content => {
  if (!editor || content === editorText) return
  if (editor.state.doc.toString() === content) return
  editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: content } })
  measure()
})
const filename = computed(() => doc.path.split(/[\\/]/).pop() || '未命名')
// user:“修”+(另存为后所有共享视图同步目标路径，避免其他标签继续保存到原文件)。
watch(() => doc.path, path => {
  savePath.value = path
  props.tab.resource = path
  props.tab.title = filename.value
})
async function save() {
  if (!savePath.value.trim()) { doc.error = '请先填写项目内的保存路径'; return }
  if (await view.save(savePath.value.trim())) {
    if (!dirty.value) { const proceed = pending.value; pending.value = null; proceed?.() }
  }
}
function discard() { doc.content = doc.baseline; const proceed = pending.value; pending.value = null; proceed?.() }
onMounted(async () => {
  await view.load()
  if (!host.value) return
  const ext = props.tab.resource.split('.').pop()?.toLowerCase()
  const language = ext === 'md' ? markdown() : ext === 'json' ? json() : ['js','ts','tsx','jsx','vue'].includes(ext || '') ? javascript({ typescript: ext !== 'js', jsx: true }) : []
  editorText = doc.content
  editor = new EditorView({ parent: host.value, state: EditorState.create({ doc: doc.content, extensions: [
    lineNumbers(), history(), drawSelection(), highlightActiveLine(), syntaxHighlighting(defaultHighlightStyle), language,
    keymap.of([{ key: 'Mod-s', run: () => { void save(); return true } }, ...defaultKeymap, ...historyKeymap, indentWithTab]),
    EditorView.lineWrapping, EditorView.contentAttributes.of({ 'aria-label': `编辑 ${filename.value}`, spellcheck: 'false' }),
    EditorView.updateListener.of(update => { if (update.docChanged) { editorText = update.state.doc.toString(); doc.content = editorText } }),
  ] }) })
  measure()
  if (typeof ResizeObserver !== 'undefined' && host.value) {
    resizeObserver = new ResizeObserver(measure)
    resizeObserver.observe(host.value)
  }
})
// user:“内容不见了 要向下滚动很长很长才能看见内容”+(切回标签时重新测量并刷新干净文件，恢复布局后不再停在空视口)。
watch(() => props.visible, visible => {
  if (!visible || !editor) return
  measure()
  if (!dirty.value && doc.loaded) reload()
})
onBeforeUnmount(() => {
  cancelAnimationFrame(measureFrame)
  resizeObserver?.disconnect()
  unregister(); editor?.destroy(); emit('dirty', props.tab.id, false); view.release()
})
</script>
<template>
  <div class="split-editor">
    <div class="split-content-toolbar"><input v-model="savePath" aria-label="文件保存路径" placeholder="项目内路径，例如 notes.md" spellcheck="false" /><button class="split-icon-button" type="button" title="重新读取文件" aria-label="重新读取文件" :disabled="doc.loading || doc.saving || !doc.loaded || dirty" @click="reload"><RefreshCw :size="14" /></button><button class="split-icon-button" type="button" title="保存 · Ctrl+S" aria-label="保存文件" :disabled="doc.loading || doc.saving || !doc.loaded" @click="save"><Save :size="15" /></button></div>
    <p v-if="doc.error" class="split-content-error" role="alert">{{ doc.error }}<button v-if="!doc.loaded && !doc.loading" class="split-text-button" @click="reload">重试</button></p>
    <p v-if="doc.loading" class="split-content-notice" role="status">正在打开文件…</p>
    <div ref="host" class="split-code-editor" :inert="!doc.loaded || undefined"></div>
    <footer class="split-content-status"><span>{{ filename }}</span><span>{{ dirty ? '未保存' : '已保存' }} · UTF-8</span></footer>
    <CoreConfirmDialog :open="Boolean(pending)" title="保存修改？" :detail="filename" :error="doc.error" :loading="doc.saving" confirm-label="保存并关闭" discard-label="不保存并关闭" @confirm="save" @cancel="pending = null" @discard="discard" />
  </div>
</template>
