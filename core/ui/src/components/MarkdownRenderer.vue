<template>
  <!-- One stable DOM shell for both modes. Streaming only changes how the
       content node is filled; it never swaps the root or content container. -->
  <div class="markdown-renderer" :class="{ 'markdown-renderer--streaming': streaming }">
    <div ref="contentRoot" class="markdown-renderer__content markdown-body" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { marked, type Renderer } from 'marked'
import DOMPurify from 'dompurify'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import { isExternalUrl, openExternalUrl } from '../helpers/openUrl'
import { renderAutoMathPlot } from './mathAutoPlot'

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
  if (node.tagName === 'IMG' && node instanceof HTMLElement) {
    const image = node as HTMLImageElement
    const src = image.getAttribute('src')?.trim() ?? ''
    if (/^http:\/\//i.test(src)) {
      image.removeAttribute('src')
      image.setAttribute('data-image-blocked', 'insecure-source')
      return
    }
    if (/^https:\/\//i.test(src)) {
      if (image.dataset.studyRemoteImage !== 'true') {
        image.removeAttribute('src')
        image.setAttribute('data-image-blocked', 'remote-disabled')
        return
      }
      image.setAttribute('loading', 'lazy')
      image.setAttribute('decoding', 'async')
      image.setAttribute('referrerpolicy', 'no-referrer')
      if (!image.getAttribute('alt')?.trim()) image.setAttribute('alt', '教学配图')
    }
  }
})

const props = withDefaults(
  defineProps<{
    content: string
    /** Whether to auto-render mermaid diagrams */
    mermaid?: boolean
    /** Render safe deterministic plots after supported display-math formulas. */
    autoPlotMath?: boolean
    /** When true, use lightweight rendering (plain text + soft line breaks) to
     *  avoid jitter from incomplete Markdown during streaming. Full Markdown
     *  rendering is applied when streaming ends. */
    streaming?: boolean
  }>(),
  {
    mermaid: true,
    autoPlotMath: false,
    streaming: false,
  },
)

const contentRoot = ref<HTMLElement | null>(null)
let tableCleanup: Array<() => void> = []

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
const inlineMathPlots: { id: string; html: string }[] = []
let inlineMathPlotSeq = 0
// Content → rendered HTML cache (see renderedHtml for rationale). Entries keep
// the mermaid blocks captured during parsing so cached hits still render
// diagrams.
const markdownCache = new Map<string, {
  html: string
  blocks: { id: string; code: string }[]
  seq: number
  inlinePlots: { id: string; html: string }[]
  inlinePlotSeq: number
}>()

// ── Code block copy button ──
// Inline lucide Copy / Check icons (same geometry as the <Copy>/<Check>
// components used elsewhere: 15px, stroke-width 1.8). Buttons live inside
// rendered HTML strings so Vue components are not an option here; the raw
// source travels in a hidden sibling element (see copyButtonHtml) and clicks
// are handled by delegation on the root.
const COPY_ICON =
  '<svg class="code-copy-icon" xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<rect width="13" height="13" x="9" y="9" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>'
const DONE_ICON =
  '<svg class="code-copy-icon code-copy-icon--done" xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M20 6 9 17l-5-5"></path></svg>'

const STUDY_SVG_MAX_LENGTH = 100_000
const STUDY_SVG_MAX_ELEMENTS = 1_000
const STUDY_SVG_STYLE_PROPERTIES = new Set([
  'dominant-baseline',
  'fill',
  'fill-opacity',
  'font-family',
  'font-size',
  'font-weight',
  'opacity',
  'stroke',
  'stroke-dasharray',
  'stroke-linecap',
  'stroke-linejoin',
  'stroke-opacity',
  'stroke-width',
  'text-anchor',
])

// Diagrams authored for a white page commonly hard-code near-black paint.
// The Study surface is dark by default, so those paths technically render but
// become indistinguishable from the card.  Treat only the conventional black
// foreground spellings as semantic text color; real accent colors are kept.
const STUDY_SVG_THEME_FOREGROUND = /^(?:#0{3}(?:000)?|#1{3}(?:111)?|black|rgb\(\s*(?:0\s*,\s*){2}0\s*\)|rgb\(\s*(?:17\s*,\s*){2}17\s*\))$/i

function adaptStudySvgPaintToTheme(elements: Element[]): void {
  for (const element of elements) {
    for (const name of ['color', 'fill', 'stroke']) {
      const value = element.getAttribute(name)?.trim() ?? ''
      if (STUDY_SVG_THEME_FOREGROUND.test(value)) element.setAttribute(name, 'currentColor')
    }
  }
}

function inlineSafeSvgStyles(source: string): string | null {
  const documentNode = new DOMParser().parseFromString(source, 'image/svg+xml')
  const svg = documentNode.documentElement
  if (svg.localName !== 'svg' || documentNode.querySelector('parsererror')) return null
  for (const style of Array.from(svg.querySelectorAll('style'))) {
    const css = style.textContent ?? ''
    for (const rule of css.split('}')) {
      const separator = rule.indexOf('{')
      if (separator < 0) continue
      const selectors = rule.slice(0, separator).split(',').map((value) => value.trim())
      const declarations = rule.slice(separator + 1).split(';')
      const safeSelectors = selectors.filter((selector) => /^(?:[a-z][\w-]*|\.[\w-]+|#[\w-]+)$/i.test(selector))
      if (safeSelectors.length === 0) continue
      const safeDeclarations: Array<[string, string]> = []
      for (const declaration of declarations) {
        const declarationSeparator = declaration.indexOf(':')
        if (declarationSeparator < 0) continue
        const property = declaration.slice(0, declarationSeparator).trim().toLowerCase()
        const value = declaration.slice(declarationSeparator + 1).trim()
        if (property === 'font') {
          const font = value.match(/^([0-9.]+(?:px|pt|em|rem|%))\s+([\w\s,'"-]+)$/i)
          if (font) safeDeclarations.push(['font-size', font[1]], ['font-family', font[2]])
          continue
        }
        if (
          STUDY_SVG_STYLE_PROPERTIES.has(property)
          && value
          && !/[<>{}]/.test(value)
          && !/(?:url\s*\(|javascript:|data:|https?:|@import|expression\s*\()/i.test(value)
        ) safeDeclarations.push([property, value])
      }
      for (const selector of safeSelectors) {
        const matches = [
          ...(svg.matches(selector) ? [svg] : []),
          ...Array.from(svg.querySelectorAll(selector)),
        ]
        for (const element of matches) {
          for (const [property, value] of safeDeclarations) element.setAttribute(property, value)
        }
      }
    }
    style.remove()
  }
  return new XMLSerializer().serializeToString(svg)
}

function sanitizeStudySvg(source: string): string | null {
  if (!props.autoPlotMath || !source.trim() || source.length > STUDY_SVG_MAX_LENGTH) return null
  const normalized = inlineSafeSvgStyles(source)
  if (!normalized) return null
  const sanitized = DOMPurify.sanitize(normalized, {
    USE_PROFILES: { svg: true },
    FORBID_TAGS: [
      'a',
      'animate',
      'animateMotion',
      'animateTransform',
      'foreignObject',
      'image',
      'script',
      'set',
      'style',
      'use',
    ],
    FORBID_ATTR: ['href', 'src', 'style', 'xlink:href'],
  })
  const documentNode = new DOMParser().parseFromString(sanitized, 'image/svg+xml')
  const svg = documentNode.documentElement
  if (svg.localName !== 'svg' || documentNode.querySelector('parsererror')) return null
  const elements = [svg, ...Array.from(svg.querySelectorAll('*'))]
  if (elements.length > STUDY_SVG_MAX_ELEMENTS) return null
  for (const element of elements) {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase()
      const value = attribute.value.trim()
      if (
        name.startsWith('on')
        || /(?:javascript|data|file|blob|https?):/i.test(value)
        || (/url\s*\(/i.test(value) && !/^url\s*\(\s*#[^)]+\s*\)$/i.test(value))
      ) {
        element.removeAttribute(attribute.name)
      }
    }
  }
  adaptStudySvgPaintToTheme(elements)
  svg.setAttribute('class', `${svg.getAttribute('class') ?? ''} study-inline-svg__graphic`.trim())
  svg.setAttribute('role', 'img')
  if (!svg.getAttribute('aria-label')) {
    const title = svg.querySelector('title')?.textContent?.trim()
    svg.setAttribute('aria-label', title || '教学示意图')
  }
  return new XMLSerializer().serializeToString(svg)
}

function copyButtonHtml(source: string): string {
  // The raw source rides in a hidden sibling element: DOMPurify drops
  // attribute values containing `-->` or closing-tag sequences
  // (SAFE_FOR_XML), so a data attribute is not a reliable carrier for
  // arbitrary code — mermaid edges alone would lose every copy source.
  // A hidden span keeps the escaped text byte-for-byte and is in the
  // default allowlist. (Note: never write a literal closing-script tag in
  // this comment — the SFC parser treats it as the end of the script block.)
  return (
    `<button type="button" class="code-copy" data-code-copy aria-label="复制代码" title="复制代码">${COPY_ICON}${DONE_ICON}</button>` +
    `<span class="code-source" hidden>${escapeHtml(source)}</span>`
  )
}

function renderMarkdownDocument(source: string): string {
  // Nested markdown document (```markdown / ```md): run the same pipeline as
  // the top level — math protection → marked → sanitize → math restore — so
  // inner formulas, diagrams and code blocks behave identically. Inner tokens
  // are restored before returning, so the outer restoreMath never sees them.
  const math = protectMath(source)
  const renderer = createMermaidRenderer()
  const html = marked.parse(math.content, {
    renderer,
    async: false,
    breaks: false,
    gfm: true,
  }) as string
  return DOMPurify.sanitize(restoreMath(html, math.tokens))
}

function createMermaidRenderer(): Renderer {
  const renderer = new marked.Renderer()

  renderer.image = function ({ href, title, text }: { href: string; title?: string | null; text: string }): string {
    const remote = /^https?:\/\//i.test(href)
    if (remote && !props.autoPlotMath) {
      return `<span class="markdown-image-fallback" role="status">远程图片仅在 Study 中显示：${escapeHtml(text || '配图')}</span>`
    }
    const titleAttr = title ? ` title="${escapeHtml(title)}"` : ''
    const studyAttr = /^https:\/\//i.test(href) ? ' data-study-remote-image="true"' : ''
    return `<img src="${escapeHtml(href)}" alt="${escapeHtml(text)}"${titleAttr}${studyAttr}>`
  }

  renderer.code = function ({ text, lang }: { text: string; lang?: string }): string {
    if (props.mermaid && lang === 'mermaid') {
      const id = `mermaid-${mermaidSeq++}`
      mermaidBlocks.push({ id, code: text })
      // The placeholder is later replaced by the rendered diagram (or the
      // error fallback); the copy button is its sibling and survives that.
      return `<div class="code-block"><div class="mermaid-placeholder" data-mermaid-id="${id}"></div>${copyButtonHtml(text)}</div>`
    }
    if (lang === 'markdown' || lang === 'md') {
      return `<div class="code-block"><div class="nested-markdown">${renderMarkdownDocument(text)}</div>${copyButtonHtml(text)}</div>`
    }
    if (lang?.toLowerCase() === 'svg' && props.autoPlotMath) {
      const svg = sanitizeStudySvg(text)
      if (svg) return `<figure class="study-inline-svg">${svg}</figure>`
    }
    // Default code block
    const langAttr = lang ? ` class="language-${lang}"` : ''
    return `<div class="code-block"><pre><code${langAttr}>${escapeHtml(text)}</code></pre>${copyButtonHtml(text)}</div>`
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
    const plot = props.autoPlotMath ? renderAutoMathPlot(expression, { allowStandalone: displayMode }) : ''
    let plotHtml = plot
    if (plot && !displayMode) {
      const id = `math-inline-plot-${inlineMathPlotSeq++}`
      inlineMathPlots.push({ id, html: plot })
      plotHtml = `<span class="math-auto-plot-anchor" data-math-auto-plot-id="${id}"></span>`
    }
    tokens.push({ token, html: renderLatex(expression, displayMode) + plotHtml })
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
  return `<div class="code-block"><pre><code${langAttr}>${escapeHtml(body)}</code></pre>${copyButtonHtml(body)}</div>`
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
  const container = contentRoot.value
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

  // Streaming mode renders via renderStreamingIncremental into contentRoot —
  // the v-html path is not used (and must not re-render the whole stream).
  if (props.streaming) return ''

  // Full Markdown render after streaming ends. Cache by content: expand/collapse
  // toggles and re-renders (part auto-collapse, process groups) re-run this
  // computed with unchanged content; re-parsing marked + sanitizing on every
  // toggle made those interactions produce ~60ms long tasks on large messages.
  const cacheKey = `${props.mermaid ? 'm1' : 'm0'}:${props.autoPlotMath ? 'p1' : 'p0'}:${props.content}`
  const cached = markdownCache.get(cacheKey)
  if (cached) {
    mermaidBlocks.length = 0
    mermaidBlocks.push(...cached.blocks)
    mermaidSeq = cached.seq
    inlineMathPlots.length = 0
    inlineMathPlots.push(...cached.inlinePlots)
    inlineMathPlotSeq = cached.inlinePlotSeq
    return cached.html
  }
  mermaidBlocks.length = 0
  mermaidSeq = 0
  inlineMathPlots.length = 0
  inlineMathPlotSeq = 0
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
  markdownCache.set(cacheKey, {
    html,
    blocks: [...mermaidBlocks],
    seq: mermaidSeq,
    inlinePlots: [...inlineMathPlots],
    inlinePlotSeq: inlineMathPlotSeq,
  })
  if (markdownCache.size > 100) {
    const oldest = markdownCache.keys().next().value
    if (oldest !== undefined) markdownCache.delete(oldest)
  }
  return html
})

function renderStaticHtml(html: string): void {
  if (!contentRoot.value) return
  clearStreamedSegments()
  clearTableEnhancements()
  contentRoot.value.innerHTML = html
  renderInlineMathPlots()
  enhanceTables()
}

function renderInlineMathPlots(): void {
  const root = contentRoot.value
  if (!root || inlineMathPlots.length === 0) return
  const lastInserted = new Map<Element, Element>()
  for (const block of inlineMathPlots) {
    const anchor = root.querySelector<HTMLElement>(`[data-math-auto-plot-id="${block.id}"]`)
    if (!anchor) continue
    const container = anchor.closest('li, p, blockquote, td, th')
    const template = document.createElement('template')
    template.innerHTML = DOMPurify.sanitize(block.html)
    const figure = template.content.querySelector<HTMLElement>('.math-auto-plot')
    anchor.remove()
    if (!container || !figure) continue
    if (container.matches('li, td, th, blockquote')) container.appendChild(figure)
    else {
      const previous = lastInserted.get(container)
      if (previous) previous.after(figure)
      else container.after(figure)
      lastInserted.set(container, figure)
    }
  }
}

// Keep a real <table> intact so the browser calculates one shared column grid.
// The surrounding card owns vertical scrolling, while the dedicated scrollbar
// above the header translates wide tables horizontally.
function clearTableEnhancements(): void {
  for (const cleanup of tableCleanup) cleanup()
  tableCleanup = []
}

function enhanceTables(): void {
  const root = contentRoot.value
  if (!root) return

  for (const table of root.querySelectorAll<HTMLTableElement>('table')) {
    if (table.closest('.markdown-table-shell')) continue

    const shell = document.createElement('div')
    shell.className = 'markdown-table-shell'

    const scrollbar = document.createElement('div')
    scrollbar.className = 'markdown-table-scrollbar'
    scrollbar.tabIndex = 0
    scrollbar.setAttribute('role', 'region')
    scrollbar.setAttribute('aria-label', '横向滚动表格')

    const scrollTrack = document.createElement('div')
    scrollTrack.className = 'markdown-table-scroll-track'
    scrollTrack.setAttribute('aria-hidden', 'true')
    scrollbar.appendChild(scrollTrack)

    const viewport = document.createElement('div')
    viewport.className = 'markdown-table-viewport'

    table.before(shell)
    shell.append(scrollbar, viewport)
    viewport.appendChild(table)

    const syncTablePosition = () => {
      table.style.transform = `translate3d(${-scrollbar.scrollLeft}px, 0, 0)`
    }
    const updateOverflow = () => {
      const viewportWidth = viewport.clientWidth
      const tableWidth = Math.ceil(table.scrollWidth)
      const overflowing = tableWidth > viewportWidth + 1
      shell.classList.toggle('markdown-table-shell--overflowing', overflowing)
      scrollbar.hidden = !overflowing
      scrollTrack.style.width = `${Math.max(tableWidth, viewportWidth)}px`
      if (!overflowing && scrollbar.scrollLeft !== 0) scrollbar.scrollLeft = 0
      syncTablePosition()
    }

    scrollbar.addEventListener('scroll', syncTablePosition, { passive: true })
    let resizeObserver: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(updateOverflow)
      resizeObserver.observe(viewport)
      resizeObserver.observe(table)
    } else {
      window.addEventListener('resize', updateOverflow)
    }
    updateOverflow()

    tableCleanup.push(() => {
      scrollbar.removeEventListener('scroll', syncTablePosition)
      resizeObserver?.disconnect()
      if (!resizeObserver) window.removeEventListener('resize', updateOverflow)
    })
  }
}

// ── Render mermaid diagrams after DOM update ──
async function renderMermaidDiagrams() {
  if (!contentRoot.value || mermaidBlocks.length === 0) return
  const mermaid = await ensureMermaid()
  if (!mermaid) return

  const placeholders = contentRoot.value.querySelectorAll<HTMLElement>('.mermaid-placeholder')
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

watch(renderedHtml, async (html) => {
  await nextTick()
  if (props.streaming) return
  renderStaticHtml(html)
  await renderMermaidDiagrams()
})

// Streaming ticks: incrementally render only the tail segment. flush:'post'
// guarantees contentRoot is mounted/updated before we touch its children.
watch(() => props.content, (value) => {
  if (props.streaming) renderStreamingIncremental(value)
}, { flush: 'post' })

// Leaving streaming mode keeps the same content node and replaces only its
// contents with the static renderer output.
watch(() => props.streaming, (streaming) => {
  if (!streaming) clearStreamedSegments()
})

// ── Code block copy (delegated; buttons live inside rendered HTML) ──
let copiedButton: HTMLElement | null = null
let copyResetTimer: ReturnType<typeof setTimeout> | null = null

function fallbackCopyText(text: string): void {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  try {
    document.execCommand('copy')
  } catch {
    // ignore — clipboard stays unavailable
  }
  textarea.remove()
}

function handleCodeCopyClick(button: HTMLElement): void {
  if (copiedButton && copiedButton !== button) copiedButton.removeAttribute('data-copied')
  if (copyResetTimer) clearTimeout(copyResetTimer)
  copiedButton = button
  button.setAttribute('data-copied', '')
  copyResetTimer = setTimeout(() => {
    button.removeAttribute('data-copied')
    if (copiedButton === button) copiedButton = null
  }, 1400)
  const source = button.closest('.code-block')?.querySelector('.code-source')?.textContent ?? ''
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(source).catch(() => fallbackCopyText(source))
  } else {
    fallbackCopyText(source)
  }
}

// ── Intercept link clicks so they open in the system browser ──
// The Tauri webview has no navigation policy; without this, clicking any
// `<a href>` navigates the app window itself. We only hijack external
// http(s) links — relative anchors are left alone.
function onRootClick(event: MouseEvent) {
  const element = event.target as HTMLElement
  const copyButton = element?.closest?.('[data-code-copy]') as HTMLElement | null
  if (copyButton) {
    event.preventDefault()
    event.stopPropagation()
    handleCodeCopyClick(copyButton)
    return
  }
  const target = element?.closest?.('a')
  if (!target) return
  const href = target.getAttribute('href') ?? ''
  if (!isExternalUrl(href)) return
  // Hand off to the OS browser and block the in-app navigation.
  event.preventDefault()
  event.stopPropagation()
  openExternalUrl(href)
}

function onRootImageError(event: Event) {
  const image = event.target
  if (!(image instanceof HTMLImageElement) || image.dataset.fallbackShown === 'true') return
  image.dataset.fallbackShown = 'true'
  image.hidden = true
  const fallback = document.createElement('span')
  fallback.className = 'markdown-image-fallback'
  fallback.setAttribute('role', 'status')
  fallback.textContent = `图片加载失败：${image.alt || '教学配图'}`
  image.after(fallback)
}

onMounted(async () => {
  contentRoot.value?.addEventListener('click', onRootClick, true)
  contentRoot.value?.addEventListener('error', onRootImageError, true)
  if (props.streaming) renderStreamingIncremental(props.content)
  else renderStaticHtml(renderedHtml.value)
  await renderMermaidDiagrams()
})

onBeforeUnmount(() => {
  contentRoot.value?.removeEventListener('click', onRootClick, true)
  contentRoot.value?.removeEventListener('error', onRootImageError, true)
  clearTableEnhancements()
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

/* Keep prose at a comfortable reading measure while allowing code, tables,
   diagrams, and other structured output to use the full response width. */
.markdown-body :deep(p),
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4),
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  max-width: 72ch;
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

/* Code block copy button — hover-reveal, same interaction pattern as the
   assistant message action bar. The button overlays the pre's top-right. */
.markdown-body :deep(.code-block) {
  position: relative;
}
/* Hidden carrier for the copy source — never rendered */
.markdown-body :deep(.code-source) {
  display: none;
}
.markdown-body :deep(.code-copy) {
  position: absolute;
  top: 6px;
  right: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #fff) 46%, transparent);
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--dur-base) var(--ease-out), background-color var(--dur-base) var(--ease-out), color var(--dur-base) var(--ease-out), transform var(--dur-fast) var(--ease-out);
}
.markdown-body :deep(.code-block:hover .code-copy),
.markdown-body :deep(.code-block:focus-within .code-copy) {
  opacity: 1;
  pointer-events: auto;
}
.markdown-body :deep(.code-copy:hover),
.markdown-body :deep(.code-copy:focus-visible) {
  background: color-mix(in srgb, var(--theme-main-text, #fff) var(--alpha-hover), transparent);
  color: var(--theme-main-text, #fff);
}
.markdown-body :deep(.code-copy:focus-visible) {
  outline: 2px solid var(--blue, #79bcff);
  outline-offset: 1px;
}
.markdown-body :deep(.code-copy svg) {
  width: 15px;
  height: 15px;
}
/* Copy → check swap while the source is on the clipboard */
.markdown-body :deep(.code-copy .code-copy-icon--done) {
  display: none;
}
.markdown-body :deep(.code-copy[data-copied] .code-copy-icon) {
  display: none;
}
.markdown-body :deep(.code-copy[data-copied] .code-copy-icon--done) {
  display: block;
}
.markdown-body :deep(.code-copy[data-copied]) {
  color: var(--green, #32d17d);
}
@media (prefers-reduced-motion: reduce) {
  .markdown-body :deep(.code-copy) {
    transition: none;
  }
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
  max-width: 72ch;
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

/* Source-backed instructional images. Remote requests are constrained by the
   sanitizer hook and desktop CSP; source attribution stays as normal prose. */
.markdown-body :deep(img) {
  display: block;
  width: auto;
  max-width: min(100%, 720px);
  max-height: min(62vh, 720px);
  margin: var(--space-3) 0 var(--space-2);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  object-fit: contain;
  background: var(--theme-main-soft-background);
}
.markdown-body :deep(img[data-image-blocked]) {
  display: none;
}
.markdown-body :deep(.markdown-image-fallback) {
  display: block;
  margin: var(--space-2) 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius-sm);
  color: color-mix(in srgb, var(--theme-main-text) 65%, transparent);
  background: var(--theme-main-soft-background);
}

/* Tables render as self-contained cards. The card viewport owns vertical
   scrolling, so its header can stick without interacting with the thread's
   top fade mask. */
.markdown-body :deep(.markdown-table-shell) {
  position: relative;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  margin: var(--space-2) 0;
  padding: var(--space-3);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-background);
}
.markdown-body :deep(.code-copy:active) {
  background: color-mix(in srgb, var(--theme-main-text, #fff) var(--alpha-active), transparent);
  transform: scale(.96);
}
.markdown-body :deep(.markdown-table-scrollbar) {
  position: relative;
  height: var(--space-3);
  overflow-x: auto;
  overflow-y: hidden;
  background: var(--theme-main-solid, var(--theme-main-background));
}
.markdown-body :deep(.markdown-table-scrollbar[hidden]) {
  display: none;
}
.markdown-body :deep(.markdown-table-scroll-track) {
  height: 1px;
}
.markdown-body :deep(.markdown-table-viewport) {
  width: 100%;
  max-width: 100%;
  max-height: min(60vh, 480px);
  min-width: 0;
  overflow-x: clip;
  overflow-y: auto;
}
.markdown-body :deep(table) {
  border-collapse: collapse;
  width: max-content;
  min-width: 100%;
  max-width: none;
  margin: 0;
  table-layout: auto;
  transform-origin: left top;
}
.markdown-body :deep(thead) {
  position: sticky;
  top: 0;
  z-index: var(--z-background-info);
  background: var(--theme-main-solid, var(--theme-main-background));
}
.markdown-body :deep(.markdown-table-shell--overflowing thead) {
  top: 0;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 12%, transparent);
  padding: 6px 10px;
  text-align: left;
  font-size: 13px;
}
.markdown-body :deep(th) {
  background: var(--theme-main-soft-background);
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

/* Study-only fenced SVG diagrams are sanitized before entering the document.
   They reuse the main content surface and remain responsive like Mermaid. */
.markdown-body :deep(.study-inline-svg) {
  width: min(100%, 720px);
  margin: var(--space-3) auto;
  color: var(--theme-main-text, #f2efeb);
}
.markdown-body :deep(.study-inline-svg__graphic) {
  display: block;
  width: 100%;
  height: auto;
  max-height: min(62vh, 720px);
  overflow: hidden;
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius-sm);
  background: var(--theme-main-soft-background);
}

/* Deterministic Study plots generated from supported display-math formulas. */
.markdown-body :deep(.math-auto-plot-anchor) { display: none; }
.markdown-body :deep(.math-auto-plot) {
  width: min(100%, 720px);
  margin: var(--space-3) auto;
  color: var(--theme-main-text, #f2efeb);
}
.markdown-body :deep(.math-auto-plot svg) {
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: 2 / 1;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 10%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 2%, transparent);
}
.markdown-body :deep(.math-auto-plot-grid) {
  stroke: color-mix(in srgb, var(--theme-main-text, #f2efeb) 10%, transparent);
  stroke-width: 1;
}
.markdown-body :deep(.math-auto-plot-axis) {
  stroke: color-mix(in srgb, var(--theme-main-text, #f2efeb) 45%, transparent);
  stroke-width: 1.2;
}
.markdown-body :deep(.math-auto-plot-limit-guide) {
  stroke: color-mix(in srgb, var(--theme-main-text, #f2efeb) 34%, transparent);
  stroke-width: 1;
  stroke-dasharray: 5 5;
}
.markdown-body :deep(.math-auto-plot-limit-point) {
  fill: var(--theme-main-background, #111);
  stroke: var(--blue);
  stroke-width: 2.2;
  vector-effect: non-scaling-stroke;
}
.markdown-body :deep(.math-auto-plot-limit-label) {
  fill: var(--theme-main-text, #f2efeb);
  font-weight: 650;
}
.markdown-body :deep(.math-auto-plot-label) {
  fill: color-mix(in srgb, var(--theme-main-text, #f2efeb) 62%, transparent);
  font: 10px var(--font-mono);
}
.markdown-body :deep(.math-auto-plot-series) {
  fill: none;
  stroke: var(--blue);
  stroke-width: 2.2;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}
.markdown-body :deep(.math-auto-plot-series--1) { stroke: var(--orange); }
.markdown-body :deep(.math-auto-plot-series--2) { stroke: var(--green); }
.markdown-body :deep(circle.math-auto-plot-series),
.markdown-body :deep(.math-auto-plot-series circle) {
  fill: currentColor;
  stroke: var(--theme-main-background, #111);
  stroke-width: 1.2;
}
.markdown-body :deep(.math-auto-plot-series--0 circle) { color: var(--blue); }
.markdown-body :deep(.math-auto-plot-series--1 circle) { color: var(--orange); }
.markdown-body :deep(.math-auto-plot-series--2 circle) { color: var(--green); }
.markdown-body :deep(.math-auto-plot figcaption) {
  margin-top: var(--space-1);
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 62%, transparent);
  font-size: 11px;
  text-align: center;
}
</style>

