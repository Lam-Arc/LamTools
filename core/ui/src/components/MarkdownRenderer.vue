<template>
  <!-- Streaming: incremental DOM rendering (only the tail segment is rebuilt
       per tick — full innerHTML replacement was O(content) per frame and made
       long streams stutter). Non-streaming keeps the single-shot v-html. -->
  <div v-if="streaming" ref="streamRoot" class="markdown-body" />
  <div v-else ref="root" class="markdown-body" v-html="renderedHtml" />
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { marked, type Renderer } from 'marked'
import DOMPurify from 'dompurify'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { isExternalUrl, openExternalUrl } from '../helpers/openUrl'

defineOptions({ name: 'MarkdownRenderer' })

// Force every rendered anchor to open externally with safe rel attributes.
// The click handler below is the primary guard (it intercepts and calls the
// OS browser); this hook covers middle-click / right-click / keyboard
// activation so those never navigate the webview either.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node instanceof HTMLElement) {
    const anchor = node as HTMLAnchorElement
    anchor.setAttribute('target', '_blank')
    anchor.setAttribute('rel', 'noopener noreferrer')
  }
})

const props = withDefaults(
  defineProps<{
    content: string
    /** Whether to auto-render mermaid diagrams */
    mermaid?: boolean
    /** When true, use lightweight rendering (plain text + soft line breaks) to
     *  avoid jitter from incomplete Markdown during streaming. Full Markdown
     *  rendering is applied when streaming ends. */
    streaming?: boolean
  }>(),
  {
    mermaid: true,
    streaming: false,
  },
)

const root = ref<HTMLElement | null>(null)
const streamRoot = ref<HTMLElement | null>(null)

// ── Mermaid init ──
let mermaidApi: typeof import('mermaid').default | null = null
let mermaidLoading: Promise<typeof import('mermaid').default | null> | null = null

async function ensureMermaid() {
  if (!props.mermaid) return null
  if (mermaidApi) return mermaidApi
  if (!mermaidLoading) {
    mermaidLoading = import('mermaid')
      .then((module) => {
        const api = module.default
        api.initialize({
          startOnLoad: false,
          theme: 'dark',
          securityLevel: 'sandbox',
          fontFamily: 'inherit',
        })
        mermaidApi = api
        return api
      })
      .catch(() => null)
  }
  return mermaidLoading
}

// ── Marked setup ──
// Collect mermaid blocks during parsing so we can replace them with
// placeholder divs that get rendered after mount.
const mermaidBlocks: { id: string; code: string }[] = []
let mermaidSeq = 0
// Content → rendered HTML cache (see renderedHtml for rationale). Entries keep
// the mermaid blocks captured during parsing so cached hits still render
// diagrams.
const markdownCache = new Map<string, { html: string; blocks: { id: string; code: string }[]; seq: number }>()

function createMermaidRenderer(): Renderer {
  const renderer = new marked.Renderer()

  renderer.code = function ({ text, lang }: { text: string; lang?: string }): string {
    if (props.mermaid && lang === 'mermaid') {
      const id = `mermaid-${mermaidSeq++}`
      mermaidBlocks.push({ id, code: text })
      return `<div class="mermaid-placeholder" data-mermaid-id="${id}"></div>`
    }
    // Default code block
    const langAttr = lang ? ` class="language-${lang}"` : ''
    return `<pre><code${langAttr}>${escapeHtml(text)}</code></pre>`
  }

  return renderer
}

function escapeHtml(text: string): string {
  // Single pass, byte-identical to the previous four sequential replaces
  // (& < > " only — single quotes are intentionally left untouched).
  return text.replace(/[&<>"]/g, (char) => {
    switch (char) {
      case '&': return '&amp;'
      case '<': return '&lt;'
      case '>': return '&gt;'
      default: return '&quot;'
    }
  })
}

function renderLatex(source: string, displayMode: boolean): string {
  try {
    return katex.renderToString(source, {
      displayMode,
      throwOnError: false,
      strict: false,
      output: 'html',
    })
  } catch {
    return escapeHtml(source)
  }
}

interface MathToken {
  token: string
  html: string
}

function splitFencedCode(content: string): Array<{ code: boolean; text: string }> {
  const result: Array<{ code: boolean; text: string }> = []
  const pattern = /```[\s\S]*?```/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(content)) !== null) {
    if (match.index > lastIndex) result.push({ code: false, text: content.slice(lastIndex, match.index) })
    result.push({ code: true, text: match[0] })
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < content.length) result.push({ code: false, text: content.slice(lastIndex) })
  return result
}

function protectMath(content: string): { content: string; tokens: MathToken[] } {
  const tokens: MathToken[] = []
  let index = 0
  const protect = (source: string, expression: string, displayMode: boolean) => {
    const token = `@@LAM_MATH_${index++}@@`
    tokens.push({ token, html: renderLatex(expression, displayMode) })
    return token
  }
  const transformed = splitFencedCode(content).map((segment) => {
    if (segment.code) return segment.text
    return segment.text
      .replace(/\\\[([\s\S]+?)\\\]/g, (_match, expression) => protect(_match, expression, true))
      .replace(/\$\$([\s\S]+?)\$\$/g, (_match, expression) => protect(_match, expression, true))
      .replace(/\\\(([\s\S]+?)\\\)/g, (_match, expression) => protect(_match, expression, false))
      .replace(/(^|[^\\$])\$([^\n$]+?)\$/g, (_match, prefix, expression) => `${prefix}${protect(_match, expression, false)}`)
  }).join('')
  return { content: transformed, tokens }
}

function restoreMath(content: string, tokens: MathToken[]): string {
  return tokens.reduce((html, item) => html.replaceAll(item.token, item.html), content)
}

function normalizeMarkdownLineBreaks(content: string): string {
  // NOTE: a single combined pass would be wrong — trailing/leading whitespace
  // around the same newline overlap (e.g. " \n "), and replace() cannot
  // consume overlapping matches. The sequential passes are the verified
  // equivalent form.
  return content
    .replace(/\r\n?/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
}

function renderStreamingInline(content: string): string {
  const { content: protectedContent, tokens } = protectMath(content)
  const escaped = escapeHtml(protectedContent)
  // Convert inline `code` → styled span
  const withCode = escaped.replace(/`([^`]+)`/g, '<code>$1</code>')
  // Convert **bold** → <strong>
  return restoreMath(withCode.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>'), tokens)
}

function renderStreamingCodeBlock(block: string): string {
  const lines = block.split('\n')
  const opening = lines[0] ?? ''
  const lang = opening.replace(/^```/, '').trim()
  const body = lines.slice(1).join('\n').replace(/\n?```$/, '')
  const langAttr = lang ? ` class="language-${escapeHtml(lang)}"` : ''
  return `<pre><code${langAttr}>${escapeHtml(body)}</code></pre>`
}

function renderStreamingBlock(block: string): string {
  const trimmed = block.trim()
  if (!trimmed) return ''

  if (trimmed.startsWith('```')) {
    return renderStreamingCodeBlock(trimmed)
  }

  const lines = trimmed.split('\n').map((line) => line.trim()).filter(Boolean)
  if (lines.length > 0 && lines.every((line) => /^[-*+]\s+/.test(line))) {
    const items = lines
      .map((line) => line.replace(/^[-*+]\s+/, ''))
      .map((line) => `<li>${renderStreamingInline(line)}</li>`)
      .join('')
    return `<ul>${items}</ul>`
  }

  if (lines.length > 0 && lines.every((line) => /^\d+[.)]\s+/.test(line))) {
    const items = lines
      .map((line) => line.replace(/^\d+[.)]\s+/, ''))
      .map((line) => `<li>${renderStreamingInline(line)}</li>`)
      .join('')
    return `<ol>${items}</ol>`
  }

  const paragraph = trimmed.replace(/\n+/g, ' ')
  return `<p>${renderStreamingInline(paragraph)}</p>`
}

// ── Lightweight streaming render ──
// During streaming, render stable paragraphs, simple lists, code blocks, and inline code.
// Single newlines remain soft line breaks so source wrapping does not create visual gaps.

// Incremental streaming: streaming content only ever grows at the tail, and
// block boundaries (blank-line separators) never retroactively change an
// already-closed segment — so segments rendered in a previous tick keep their
// exact DOM nodes forever. Only the final (open) segment is rebuilt each tick.
// This turns per-frame cost from O(whole content) into O(tail segment).
interface StreamedSegment {
  text: string
  nodes: ChildNode[]
}

let streamedSegments: StreamedSegment[] = []

function clearStreamedSegments(): void {
  for (const segment of streamedSegments) {
    for (const node of segment.nodes) node.remove()
  }
  streamedSegments = []
}

function renderStreamingIncremental(content: string): void {
  const container = streamRoot.value
  if (!container) return
  const blocks = normalizeMarkdownLineBreaks(content).split(/\n{2,}/)
  const segments = streamedSegments

  // Reuse every segment whose text is byte-identical to the previous tick.
  let index = 0
  while (index < blocks.length && index < segments.length && blocks[index] === segments[index].text) {
    index += 1
  }

  // Drop now-obsolete tail segments (the previously-open segment changed).
  while (segments.length > index) {
    const removed = segments.pop()!
    for (const node of removed.nodes) node.remove()
  }

  // Render only the new/changed tail segments and append their nodes in DOM
  // order (identical structure to the old single v-html string).
  const temp = document.createElement('div')
  while (index < blocks.length) {
    temp.innerHTML = renderStreamingBlock(blocks[index])
    const nodes: ChildNode[] = []
    while (temp.firstChild) {
      const child = temp.removeChild(temp.firstChild)
      container.appendChild(child)
      nodes.push(child)
    }
    segments.push({ text: blocks[index], nodes })
    index += 1
  }
}

// ── Lightweight streaming render (string form) ──
// Exposed via defineExpose for equivalence testing against the incremental
// DOM renderer.
function renderStreaming(content: string): string {
  return normalizeMarkdownLineBreaks(content)
    .split(/\n{2,}/)
    .map(renderStreamingBlock)
    .join('')
}

const renderedHtml = computed(() => {
  if (!props.content) return ''

  // Streaming mode renders via renderStreamingIncremental into streamRoot —
  // the v-html path is not used (and must not re-render the whole stream).
  if (props.streaming) return ''

  // Full Markdown render after streaming ends. Cache by content: expand/collapse
  // toggles and re-renders (part auto-collapse, process groups) re-run this
  // computed with unchanged content; re-parsing marked + sanitizing on every
  // toggle made those interactions produce ~60ms long tasks on large messages.
  const cached = markdownCache.get(props.content)
  if (cached) {
    mermaidBlocks.length = 0
    mermaidBlocks.push(...cached.blocks)
    mermaidSeq = cached.seq
    return cached.html
  }
  mermaidBlocks.length = 0
  mermaidSeq = 0
  let html: string
  try {
    const math = protectMath(props.content)
    const renderer = createMermaidRenderer()
    html = marked.parse(math.content, {
      renderer,
      async: false,
      breaks: false,
      gfm: true,
    }) as string
    html = DOMPurify.sanitize(restoreMath(html, math.tokens))
  } catch {
    html = `<p>${escapeHtml(props.content)}</p>`
  }
  markdownCache.set(props.content, { html, blocks: [...mermaidBlocks], seq: mermaidSeq })
  if (markdownCache.size > 100) {
    const oldest = markdownCache.keys().next().value
    if (oldest !== undefined) markdownCache.delete(oldest)
  }
  return html
})

// ── Render mermaid diagrams after DOM update ──
async function renderMermaidDiagrams() {
  if (!root.value || mermaidBlocks.length === 0) return
  const mermaid = await ensureMermaid()
  if (!mermaid) return

  const placeholders = root.value.querySelectorAll<HTMLElement>('.mermaid-placeholder')
  for (const placeholder of placeholders) {
    const id = placeholder.dataset.mermaidId
    const block = mermaidBlocks.find((b) => b.id === id)
    if (!block) continue
    try {
      const { svg } = await mermaid.render(`mermaid-svg-${id}`, block.code)
      placeholder.outerHTML = `<div class="mermaid-diagram">${svg}</div>`
    } catch {
      placeholder.outerHTML = `<pre class="mermaid-error"><code>${escapeHtml(block.code)}</code></pre>`
    }
  }
}

watch(renderedHtml, async () => {
  await nextTick()
  await renderMermaidDiagrams()
})

// Streaming ticks: incrementally render only the tail segment. flush:'post'
// guarantees streamRoot is mounted/updated before we touch its children.
watch(() => props.content, (value) => {
  if (props.streaming) renderStreamingIncremental(value)
}, { flush: 'post' })

// Leaving streaming mode hands the DOM back to the v-html branch; drop the
// incremental state (the streamRoot subtree is destroyed by the v-if switch).
watch(() => props.streaming, (streaming) => {
  if (!streaming) clearStreamedSegments()
})

// ── Intercept link clicks so they open in the system browser ──
// The Tauri webview has no navigation policy; without this, clicking any
// `<a href>` navigates the app window itself. We only hijack external
// http(s) links — relative anchors are left alone.
function onRootClick(event: MouseEvent) {
  const target = (event.target as HTMLElement)?.closest?.('a')
  if (!target) return
  const href = target.getAttribute('href') ?? ''
  if (!isExternalUrl(href)) return
  // Hand off to the OS browser and block the in-app navigation.
  event.preventDefault()
  event.stopPropagation()
  openExternalUrl(href)
}

onMounted(async () => {
  root.value?.addEventListener('click', onRootClick, true)
  streamRoot.value?.addEventListener('click', onRootClick, true)
  if (props.streaming) renderStreamingIncremental(props.content)
  await renderMermaidDiagrams()
})

onBeforeUnmount(() => {
  root.value?.removeEventListener('click', onRootClick, true)
  streamRoot.value?.removeEventListener('click', onRootClick, true)
  clearStreamedSegments()
})

defineExpose({ renderStreaming })
</script>

<style scoped>
.markdown-body {
  font-size: 14px;
  line-height: 1.5;
  color: var(--theme-main-text, #eee);
  word-break: break-word;
}

/* Headings */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 18px 0 8px;
  line-height: 1.25;
  font-weight: 650;
}
.markdown-body :deep(h1) { font-size: 1.4em; }
.markdown-body :deep(h2) { font-size: 1.2em; }
.markdown-body :deep(h3) { font-size: 1.1em; }
.markdown-body :deep(h4) { font-size: 1em; }

/* Paragraphs */
.markdown-body :deep(p) {
  margin: 0 0 6px;
}
.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

/* Inline code */
.markdown-body :deep(code) {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 7%, transparent);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: 0.9em;
  font-family: var(--font-mono);
}

/* Code blocks */
.markdown-body :deep(pre) {
  margin: 6px 0;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 4%, transparent);
  overflow-x: auto;
}
.markdown-body :deep(pre code) {
  background: transparent;
  padding: 0;
  font-size: 13px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Lists */
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 6px 0;
  padding-left: 24px;
}
.markdown-body :deep(li) {
  margin: 2px 0;
}

/* Blockquotes */
.markdown-body :deep(blockquote) {
  margin: 6px 0;
  padding: 6px 14px;
  border-left: 3px solid color-mix(in srgb, var(--theme-main-text, var(--text, currentColor)) 22%, transparent);
  color: color-mix(in srgb, var(--theme-main-text, var(--text, currentColor)) 76%, transparent);
}

/* Links */
.markdown-body :deep(a) {
  color: var(--blue);
  text-decoration: none;
}
.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

/* Tables — like code blocks, wide tables scroll horizontally inside their
   own box instead of stretching the message column (which pushes
   right-aligned user bubbles past the viewport). display:block makes the
   table box a block scroll container; the internal auto-laid-out table keeps
   its natural column widths and scrolls when it doesn't fit. */
.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
  max-width: 100%;
  display: block;
  overflow-x: auto;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 12%, transparent);
  padding: 6px 10px;
  text-align: left;
  font-size: 13px;
}
.markdown-body :deep(th) {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 5%, transparent);
  font-weight: 600;
}

/* Horizontal rule */
.markdown-body :deep(hr) {
  border: 0;
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 8%, transparent);
  margin: 14px 0;
}

/* Mermaid diagrams */
.markdown-body :deep(.mermaid-diagram) {
  margin: 10px 0;
  display: flex;
  justify-content: center;
}
.markdown-body :deep(.mermaid-diagram svg) {
  max-width: 100%;
  height: auto;
}

/* Mermaid error fallback */
.markdown-body :deep(.mermaid-error) {
  color: color-mix(in srgb, var(--red) 55%, var(--theme-main-text, #f2efeb));
  background: color-mix(in srgb, var(--red) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--red) 20%, transparent);
}
</style>

