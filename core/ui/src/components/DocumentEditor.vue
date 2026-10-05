<template>
  <div class="doc-editor" :data-doc-editor="idPrefix">
    <!-- 工具条：作用在选中的文字上；不可用时（没选中）禁用，不做假按钮。 -->
    <div
      class="doc-editor-toolbar"
      v-bind="toolbarAttrs"
      role="toolbar"
      :aria-label="`${title} 的格式工具`"
    >
      <button
        v-for="action in ACTIONS"
        :key="action.id"
        type="button"
        class="doc-editor-tool"
        :title="action.title"
        :aria-label="action.title"
        :disabled="action.needsSelection && !hasSelection"
        :data-doc-editor-action="action.id"
        @click="apply(action)"
      ><component :is="action.icon" :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
      <span class="doc-editor-toolbar-spacer" aria-hidden="true"></span>
      <button
        type="button"
        class="doc-editor-tool doc-editor-preview-toggle"
        :class="{ active: previewing }"
        :aria-pressed="previewing"
        :title="previewing ? '回到编辑' : '预览排版'"
        :aria-label="previewing ? '回到编辑' : '预览排版'"
        v-bind="toggleAttrs"
        @click="previewing = !previewing"
      ><component :is="previewing ? PenLine : Eye" :size="14" :stroke-width="1.8" aria-hidden="true" />{{ previewing ? '编辑' : '预览' }}</button>
      <span class="doc-editor-hint" aria-hidden="true">Enter 续列表 · Tab 缩进</span>
    </div>

    <!-- 单栏：写的时候是源文，切一下才看排版——不再两栏同时占地方。 -->
    <div class="doc-editor-panes">
      <textarea
        v-if="!previewing"
        ref="input"
        v-model="draft"
        class="doc-editor-source"
        :aria-label="`编辑 ${title}`"
        v-bind="inputAttrs"
        spellcheck="false"
        @keydown="onKeydown"
        @select="trackSelection"
        @keyup="trackSelection"
        @mouseup="trackSelection"
      ></textarea>

      <!-- 预览：和阅读页同一套排版，所以保存前后不会"换了个样子"。 -->
      <div v-else ref="preview" class="doc-editor-preview" v-bind="previewAttrs">
        <article class="library-document">
          <slot name="preview" :content="draft" />
        </article>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * DocumentEditor — 方案与记忆共用的文档编辑器。
 *
 * 两件事决定了它的样子：
 * 1. **阅读与编辑是一份文档的两种状态**：源文用正文的字体、字号、行高与宽度，
 *    预览用与阅读页完全相同的排版，所以进出编辑不会"换一个界面"。
 * 2. **一栏二态**：默认写源文，工具条上的「预览」键随时切换到排版结果；
 *    同一块版面在两种状态间换脸，不并排占两份地方。
 *
 * 工具条只做 Markdown 的最小语法（标题 / 粗斜体 / 列表 / 清单 / 引用 / 代码 /
 * 链接），全部作用在选中的文字上；没选中就只插入标记，不做假动作。
 */
import { computed, nextTick, ref, watch } from 'vue'
import {
  Bold,
  Code,
  Eye,
  Heading2,
  Italic,
  Link,
  List,
  ListChecks,
  ListOrdered,
  PenLine,
  Quote,
  type LucideIcon,
} from 'lucide-vue-next'

const props = defineProps<{
  /** 数据钩子前缀：两种宿主各自的测试与定位靠它区分（如 library-editor）。 */
  idPrefix: string
  /** 文档标题，仅用于无障碍标签。 */
  title: string
  /** 源文（v-model）。 */
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const draft = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value),
})

const input = ref<HTMLTextAreaElement | null>(null)
const preview = ref<HTMLElement | null>(null)
const previewing = ref(false)
// 数据钩子仍按宿主命名（library-editor / memory-editor），既有测试与定位不用改。
const inputAttrs = computed(() => ({ [`data-${props.idPrefix}-input`]: '' }))
const toolbarAttrs = computed(() => ({ [`data-${props.idPrefix}-toolbar`]: '' }))
const previewAttrs = computed(() => ({ [`data-${props.idPrefix}-preview`]: '' }))
const toggleAttrs = computed(() => ({ [`data-${props.idPrefix}-preview-toggle`]: '' }))
const hasSelection = ref(false)

/** 宿主在切换子页（保存/离开）时把编辑器拉回书写状态。 */
function setPreviewing(value: boolean): void {
  previewing.value = value
}

interface ToolAction {
  id: string
  title: string
  icon: LucideIcon
  prefix: string
  suffix?: string
  /** 行首标记：整行套用，用于列表与引用。 */
  line?: boolean
  needsSelection?: boolean
}

const ACTIONS: ToolAction[] = [
  { id: 'heading', title: '标题', icon: Heading2, prefix: '## ' },
  { id: 'bold', title: '加粗', icon: Bold, prefix: '**', suffix: '**', needsSelection: true },
  { id: 'italic', title: '斜体', icon: Italic, prefix: '*', suffix: '*', needsSelection: true },
  { id: 'list', title: '无序列表', icon: List, prefix: '- ', line: true },
  { id: 'ordered', title: '有序列表', icon: ListOrdered, prefix: '1. ', line: true },
  { id: 'checklist', title: '清单', icon: ListChecks, prefix: '- [ ] ', line: true },
  { id: 'quote', title: '引用', icon: Quote, prefix: '> ', line: true },
  { id: 'code', title: '行内代码', icon: Code, prefix: '`', suffix: '`', needsSelection: true },
  { id: 'link', title: '链接', icon: Link, prefix: '[', suffix: '](https://)', needsSelection: true },
]

function current(): HTMLTextAreaElement | null {
  return input.value
}

function trackSelection(): void {
  const element = current()
  if (!element) return
  hasSelection.value = element.selectionEnd > element.selectionStart
}

/** 用一次 replaceRange 落地，并把光标放回可继续输入的位置。 */
function replaceRange(start: number, end: number, text: string, caret = text.length): void {
  const element = current()
  if (!element) return
  const next = props.modelValue.slice(0, start) + text + props.modelValue.slice(end)
  emit('update:modelValue', next)
  void nextTick(() => {
    element.focus()
    element.setSelectionRange(start + caret, start + caret)
  })
}

function lineBounds(value: string, start: number, end: number): { from: number; to: number } {
  const from = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1
  const nextBreak = value.indexOf('\n', end)
  return { from, to: nextBreak === -1 ? value.length : nextBreak }
}

function apply(action: ToolAction): void {
  const element = current()
  if (!element) return
  const value = props.modelValue
  const start = element.selectionStart
  const end = element.selectionEnd
  const selected = value.slice(start, end)

  if (action.line) {
    const { from, to } = lineBounds(value, start, end)
    const block = value.slice(from, to)
    const lines = block.split('\n')
    // 整块已经都是这个标记就取消它——同一个键进出，不让人再去删。
    const marked = lines.every(line => line.startsWith(action.prefix))
    const next = lines
      .map(line => (marked ? line.slice(action.prefix.length) : `${action.prefix}${line}`))
      .join('\n')
    replaceRange(from, to, next)
    return
  }

  const suffix = action.suffix ?? ''
  replaceRange(start, end, `${action.prefix}${selected}${suffix}`, action.prefix.length + selected.length)
}

/** 回车续列表、Tab 缩进：都是写结构化文档时手最自然的动作。 */
function onKeydown(event: KeyboardEvent): void {
  const element = current()
  if (!element) return

  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'b') {
    event.preventDefault()
    apply(ACTIONS.find(action => action.id === 'bold')!)
    return
  }

  if (event.key === 'Enter' && !event.shiftKey && element.selectionStart === element.selectionEnd) {
    const value = props.modelValue
    const { from } = lineBounds(value, element.selectionStart, element.selectionStart)
    const line = value.slice(from, element.selectionStart)
    const match = /^(\s*)([-*] \[[ x]\] |[-*] |\d+\. |> )/.exec(line)
    if (!match) return
    // 空的列表项上回车 = 结束这个列表，而不是再开一行空的。
    if (line === `${match[1]}${match[2]}`) {
      event.preventDefault()
      replaceRange(from, element.selectionStart, '')
      return
    }
    event.preventDefault()
    const ordered = /^\d+\. $/.test(match[2])
    const marker = ordered ? `${String(Number(match[2].trim().split('.')[0]) + 1)}. ` : match[2]
    const spaces = match[1]
    const insertion = `\n${spaces}${marker}`
    replaceRange(element.selectionStart, element.selectionStart, insertion)
    return
  }

  if (event.key === 'Tab' && !event.shiftKey) {
    event.preventDefault()
    const start = element.selectionStart
    replaceRange(start, element.selectionEnd, '  ', 2)
    return
  }
  if (event.key === 'Tab' && event.shiftKey) {
    event.preventDefault()
    const value = props.modelValue
    const start = element.selectionStart
    const { from } = lineBounds(value, start, start)
    if (value.slice(from, from + 2) === '  ') {
      replaceRange(from, from + 2, '', 0)
    }
    return
  }

  void nextTick(trackSelection)
}

watch(() => props.modelValue, () => { void nextTick(trackSelection) })

defineExpose({
  focus: () => input.value?.focus(),
  setPreviewing,
})
</script>
