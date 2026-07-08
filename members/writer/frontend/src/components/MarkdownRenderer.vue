<template>
  <div ref="root" class="markdown-body" v-html="renderedHtml" />
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import { marked, type Renderer } from 'marked'
import DOMPurify from 'dompurify'
import katex from 'katex'
import 'katex/dist/katex.min.css'

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
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
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
function renderStreaming(content: string): string {
  return normalizeMarkdownLineBreaks(content)
    .split(/\n{2,}/)
    .map(renderStreamingBlock)
    .join('')
}

const renderedHtml = computed(() => {
  if (!props.content) return ''

  // Lightweight mode during streaming
  if (props.streaming) {
    return DOMPurify.sanitize(renderStreaming(props.content))
  }

  // Full Markdown render after streaming ends
  mermaidBlocks.length = 0
  mermaidSeq = 0
  try {
    const math = protectMath(props.content)
    const renderer = createMermaidRenderer()
    const html = marked.parse(math.content, {
      renderer,
      async: false,
      breaks: false,
      gfm: true,
    }) as string
    return DOMPurify.sanitize(restoreMath(html, math.tokens))
  } catch {
    return `<p>${escapeHtml(props.content)}</p>`
  }
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

onMounted(async () => {
  await renderMermaidDiagrams()
})
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
  background: rgba(255, 255, 255, 0.07);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  font-family: var(--font-mono);
}

/* Code blocks */
.markdown-body :deep(pre) {
  margin: 6px 0;
  padding: 10px 14px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
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
  color: #79bcff;
  text-decoration: none;
}
.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

/* Tables */
.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid rgba(255, 255, 255, 0.12);
  padding: 6px 10px;
  text-align: left;
  font-size: 13px;
}
.markdown-body :deep(th) {
  background: rgba(255, 255, 255, 0.05);
  font-weight: 600;
}

/* Horizontal rule */
.markdown-body :deep(hr) {
  border: 0;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
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
  color: #faa;
  background: rgba(245, 85, 93, 0.08);
  border: 1px solid rgba(245, 85, 93, 0.2);
}
</style>
