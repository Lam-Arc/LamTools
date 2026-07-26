<template>
  <div class="stage-code-editor-wrap">
    <div ref="containerEl" class="stage-code-editor"></div>
    <div v-if="dirty" class="stage-code-dirty" aria-hidden="true">●</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { EditorState, Compartment } from '@codemirror/state'
import { EditorView, keymap, lineNumbers, highlightActiveLine } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { syntaxHighlighting, defaultHighlightStyle, bracketMatching, foldGutter, indentOnInput } from '@codemirror/language'
import { oneDark } from '@codemirror/theme-one-dark'
import { javascript } from '@codemirror/lang-javascript'
import { python } from '@codemirror/lang-python'
import { markdown } from '@codemirror/lang-markdown'
import { css } from '@codemirror/lang-css'
import { json } from '@codemirror/lang-json'
import { html } from '@codemirror/lang-html'

const props = defineProps<{
  content: string
  language?: string
}>()

const emit = defineEmits<{
  'update:content': [value: string]
  dirty: [value: boolean]
  save: []
}>()

const containerEl = ref<HTMLDivElement | null>(null)
const dirty = ref(false)
let view: EditorView | null = null
let lastSavedContent = props.content
const languageCompartment = new Compartment()
const themeCompartment = new Compartment()

function getLanguageExtension(lang?: string) {
  switch (lang) {
    case 'ts':
    case 'tsx':
      return javascript({ typescript: true, jsx: lang === 'tsx' })
    case 'js':
    case 'jsx':
      return javascript({ jsx: lang === 'jsx' })
    case 'mjs':
      return javascript()
    case 'py':
      return python()
    case 'md':
    case 'markdown':
      return markdown()
    case 'css':
    case 'scss':
      return css()
    case 'json':
      return json()
    case 'html':
    case 'vue':
      return html()
    default:
      return undefined
  }
}

function createState(doc: string, lang?: string): EditorState {
  return EditorState.create({
    doc,
    extensions: [
      lineNumbers(),
      foldGutter(),
      history(),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      indentOnInput(),
      bracketMatching(),
      highlightActiveLine(),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      languageCompartment.of(getLanguageExtension(lang) ?? []),
      themeCompartment.of(oneDark),
      EditorView.lineWrapping,
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          const current = update.state.doc.toString()
          const isDirty = current !== lastSavedContent
          if (isDirty !== dirty.value) {
            dirty.value = isDirty
            emit('dirty', isDirty)
          }
          emit('update:content', current)
        }
      }),
      keymap.of([{
        key: 'Mod-s',
        preventDefault: true,
        run: () => {
          if (dirty.value) {
            emit('save')
          }
          return true
        },
      }]),
      EditorView.theme({
        '&': {
          height: '100%',
          fontSize: '13px',
          backgroundColor: 'transparent',
        },
        '.cm-scroller': {
          fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
        },
        '.cm-gutters': {
          backgroundColor: 'transparent',
          border: 'none',
        },
      }),
    ],
  })
}

onMounted(() => {
  if (containerEl.value) {
    view = new EditorView({
      state: createState(props.content, props.language),
      parent: containerEl.value,
    })
  }
})

onUnmounted(() => {
  view?.destroy()
  view = null
})

function markSaved() {
  if (view) {
    lastSavedContent = view.state.doc.toString()
  }
  if (dirty.value) {
    dirty.value = false
    emit('dirty', false)
  }
}

defineExpose({ markSaved })

// Update content when prop changes externally
watch(() => props.content, (newContent) => {
  if (!view) return
  const currentContent = view.state.doc.toString()
  if (newContent !== currentContent) {
    view.dispatch({
      changes: { from: 0, to: currentContent.length, insert: newContent },
    })
  }
})

// Update language when prop changes
watch(() => props.language, (newLang) => {
  if (!view) return
  view.dispatch({
    effects: languageCompartment.reconfigure(getLanguageExtension(newLang) ?? []),
  })
})
</script>

<style scoped>
.stage-code-editor-wrap {
  width: 100%;
  height: 100%;
  position: relative;
  overflow: hidden;
}
.stage-code-editor {
  width: 100%;
  height: 100%;
  overflow: hidden;
}
.stage-code-dirty {
  position: absolute;
  top: 6px;
  right: 10px;
  font-size: 10px;
  color: var(--orange, #e07a5b);
  pointer-events: none;
  z-index: 10;
}
.stage-code-editor :deep(.cm-editor) {
  height: 100%;
  background: transparent !important;
  color: var(--theme-main-text, #f2efeb) !important;
}
.stage-code-editor :deep(.cm-content) {
  color: var(--theme-main-text, #f2efeb) !important;
}
.stage-code-editor :deep(.cm-line) {
  color: var(--theme-main-text, #f2efeb) !important;
}
.stage-code-editor :deep(.cm-gutters) {
  background: transparent !important;
  border: none !important;
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 40%, transparent) !important;
}
.stage-code-editor :deep(.cm-gutter .cm-gutterElement) {
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 40%, transparent) !important;
}
.stage-code-editor :deep(.cm-activeLine) {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 4%, transparent) !important;
}
.stage-code-editor :deep(.cm-activeLineGutter) {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 4%, transparent) !important;
}
.stage-code-editor :deep(.cm-cursor) {
  border-left-color: var(--theme-main-text, #f2efeb) !important;
}
.stage-code-editor :deep(.cm-selectionBackground) {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 15%, transparent) !important;
}
.stage-code-editor :deep(.cm-scroller) {
  overflow: auto;
}
</style>
