import type { MarkAnchor } from './types'
import { codePointToUtf16, expandEnglishWord, utf16ToCodePoint } from './selection'

const BLOCKS = '.markdown-renderer__content, .user-bubble, [data-selection-block], p, pre, li, h1, h2, h3, td, label'
const SURFACES = ['.settings-overlay', '.editor-overlay', '.drawer-left', '.drawer-right', '.workspace-main']

function element(node: Node | null): Element | null { return node instanceof Element ? node : node?.parentElement || null }

export function splitRangeForFormulaHighlight(range: Range): { textRanges: Range[]; formulaRanges: Range[] } {
  const root = range.commonAncestorContainer
  const nodes: Text[] = []
  if (root.nodeType === Node.TEXT_NODE) nodes.push(root as Text)
  else {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    while (walker.nextNode()) nodes.push(walker.currentNode as Text)
  }

  const textRanges: Range[] = []
  const formulaRanges: Range[] = []
  for (const node of nodes) {
    if (!range.intersectsNode(node)) continue
    const start = node === range.startContainer ? range.startOffset : 0
    const end = node === range.endContainer ? range.endOffset : node.length
    if (end <= start) continue
    const fragment = document.createRange()
    fragment.setStart(node, start)
    fragment.setEnd(node, end)
    const target = element(node)?.closest('.katex') ? formulaRanges : textRanges
    target.push(fragment)
  }
  if (!formulaRanges.length) return { textRanges: [range], formulaRanges }
  return { textRanges, formulaRanges }
}

function blocks(root: Element): Element[] {
  const found = Array.from(root.querySelectorAll(BLOCKS))
  return found.filter(el => !found.some(parent => parent !== el && parent.contains(el)))
}
function textOffset(root: Element, node: Node, offset: number): number {
  const range = document.createRange(); range.selectNodeContents(root); range.setEnd(node, offset)
  return range.toString().length
}
function codePointOffset(text: string, utf16Offset: number): number {
  return utf16ToCodePoint(text, Math.max(0, Math.min(utf16Offset, text.length)))
}
function utf16Range(text: string, range: [number, number], unit = 'unicode-code-point'): [number, number] {
  return unit === 'utf-16' ? range : [codePointToUtf16(text, range[0]), codePointToUtf16(text, range[1])]
}

export function expandWord(text: string, start: number, end: number): [number, number] {
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > Array.from(text).length) return [start, end]
  try {
    const expanded = expandEnglishWord(text, { start, end })
    if (expanded.start !== start || expanded.end !== end) return [expanded.start, expanded.end]
  } catch { /* invalid/empty ranges remain unchanged for DOM callers */ }
  return [start, end]
}

export function captureAnchor(selection: Selection, sessionId: string, view: string): MarkAnchor | null {
  if (!selection.rangeCount || selection.isCollapsed) return null
  const range = selection.getRangeAt(0)
  const startEl = element(range.startContainer)
  if (startEl?.closest('input,textarea,[contenteditable],.selection-card,[data-context-menu-panel]')) return null
  const message = startEl?.closest('[data-message-id]')
  const surface = SURFACES.find(selector => startEl?.closest(selector))
  const root = message || startEl?.closest('[data-selection-document]') || (surface ? startEl?.closest(surface) : null)
  if (!root || !root.contains(range.endContainer)) return null
  const candidates = blocks(root)
  const startBlock = candidates.find(block => block.contains(range.startContainer))
  const endBlock = candidates.find(block => block.contains(range.endContainer)) || startBlock
  if (!startBlock || !endBlock) return null
  // A selection crossing independent messages is intentionally not anchored
  // ambiguously. A selection crossing blocks within one source is represented
  // as fragments so it remains relocatable after re-rendering.
  const sourceId = message?.getAttribute('data-message-id') || root.getAttribute('data-selection-document') || `view:${view}:${surface}`
  const sourceRevision = Number(root.getAttribute('data-source-revision') || root.getAttribute('data-revision') || '')
  const sourceType = message ? 'message' : 'text'
  const unit: MarkAnchor['unit'] = 'unicode-code-point'
  const orderedStart = candidates.indexOf(startBlock)
  const orderedEnd = candidates.indexOf(endBlock)
  if (orderedStart < 0 || orderedEnd < 0) return null
  const first = Math.min(orderedStart, orderedEnd)
  const last = Math.max(orderedStart, orderedEnd)
  const fragmentBlocks = candidates.slice(first, last + 1)
  const segments = fragmentBlocks.map((block, index) => {
    const full = block.textContent || ''
    const startUnit = index === 0 ? codePointOffset(full, textOffset(block, range.startContainer, range.startOffset)) : 0
    const endUnit = index === fragmentBlocks.length - 1 ? codePointOffset(full, textOffset(block, range.endContainer, range.endOffset)) : Array.from(full).length
    const [start, end] = expandWord(full, startUnit, endUnit)
    return {
      start,
      end,
      exact: full.slice(codePointToUtf16(full, start), codePointToUtf16(full, end)),
      prefix: Array.from(full).slice(Math.max(0, start - 120), start).join(''),
      suffix: Array.from(full).slice(end, end + 120).join(''),
      block_id: `${fragmentBlocks[index].closest('[data-part-id]') ? 'part:' + fragmentBlocks[index].closest('[data-part-id]')!.getAttribute('data-part-id') : 'body'}|${candidates.indexOf(fragmentBlocks[index])}`,
    }
  })
  const firstSegment = segments[0]
  const exact = segments.map(segment => segment.exact).join('\n')
  const prefix = firstSegment.prefix
  const suffix = segments.at(-1)?.suffix || ''
  return {
    document_id: sourceId,
    block_id: firstSegment.block_id || `body|${orderedStart}`,
    sourceId,
    blockId: firstSegment.block_id || `body|${orderedStart}`,
    start: firstSegment.start,
    end: firstSegment.end,
    quote: exact,
    prefix,
    suffix,
    unit,
    projection_version: 'semantic-text-v1',
    projectionVersion: 'semantic-text-v1',
    ...(Number.isFinite(sourceRevision) && sourceRevision > 0 ? { source_revision: sourceRevision } : {}),
    ...(Number.isFinite(sourceRevision) && sourceRevision > 0 ? { sourceRevision } : {}),
    ...(segments.length > 1 ? { segments } : {}),
    ...(message ? { session_id: sessionId, source_type: sourceType } : { source_type: sourceType }),
  }
}

function sliceByUnit(text: string, start: number, end: number, unit = 'unicode-code-point'): string {
  const max = unit === 'utf-16' ? text.length : Array.from(text).length
  const safeStart = Math.max(0, Math.min(start, max))
  const safeEnd = Math.max(safeStart, Math.min(end, max))
  const [utfStart, utfEnd] = utf16Range(text, [safeStart, safeEnd], unit)
  return text.slice(utfStart, utfEnd)
}

export function locateOffsets(text: string, anchor: MarkAnchor): [number, number] | null {
  const unit = anchor.unit || 'utf-16'
  if (sliceByUnit(text, anchor.start, anchor.end, unit) === anchor.quote && (!anchor.prefix || sliceByUnit(text, Math.max(0, anchor.start - Array.from(anchor.prefix).length), anchor.start, unit) === anchor.prefix)) return [anchor.start, anchor.end]
  const matches: Array<[number, number]> = []
  let index = text.indexOf(anchor.quote)
  while (index >= 0) {
    const end = index + anchor.quote.length
    if ((!anchor.prefix || text.slice(Math.max(0, index - anchor.prefix.length), index) === anchor.prefix)
      && (!anchor.suffix || text.slice(end, end + anchor.suffix.length) === anchor.suffix)) {
      const startPoint = unit === 'utf-16' ? index : codePointOffset(text, index)
      const endPoint = unit === 'utf-16' ? end : codePointOffset(text, end)
      matches.push([startPoint, endPoint])
    }
    index = text.indexOf(anchor.quote, index + 1)
  }
  return matches.length === 1 ? matches[0] : null
}

function blockFromId(root: Element, blockId: string): Element | null {
  const separator = blockId.lastIndexOf('|')
  if (separator < 0) return null
  const key = blockId.slice(0, separator)
  const index = Number(blockId.slice(separator + 1))
  const container = key.startsWith('part:') ? root.querySelector(`[data-part-id="${CSS.escape(key.slice(5))}"]`) : root
  if (!container || !Number.isInteger(index)) return null
  return blocks(container)[index] || null
}

function rangeInBlock(block: Element, anchor: MarkAnchor): Range | null {
  const offsets = locateOffsets(block.textContent || '', anchor)
  if (!offsets) return null
  const [start, end] = utf16Range(block.textContent || '', offsets, anchor.unit || 'utf-16')
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT)
  const range = document.createRange(); let pos = 0; let started = false
  while (walker.nextNode()) {
    const node = walker.currentNode
    const length = node.textContent?.length || 0
    if (!started && start <= pos + length) { range.setStart(node, Math.max(0, start - pos)); started = true }
    if (started && end <= pos + length) { range.setEnd(node, Math.max(0, end - pos)); return range }
    pos += length
  }
  return null
}

export function anchorRange(anchor: MarkAnchor): Range | null {
  const surface = SURFACES.find(selector => anchor.document_id.endsWith(':' + selector))
  const root = anchor.source_type === 'message'
    ? document.querySelector(`[data-message-id="${CSS.escape(anchor.document_id)}"]`)
    : document.querySelector(`[data-selection-document="${CSS.escape(anchor.document_id)}"]`) || (surface ? document.querySelector(surface) : null)
  if (!root) return null
  const fragments = anchor.segments
  if (fragments?.length) {
    const first = blockFromId(root, fragments[0].block_id || anchor.block_id)
    const last = blockFromId(root, fragments.at(-1)?.block_id || anchor.block_id)
    if (!first || !last) return null
    const start = rangeInBlock(first, { ...anchor, ...fragments[0], quote: fragments[0].exact, block_id: fragments[0].block_id || anchor.block_id })
    const end = rangeInBlock(last, { ...anchor, ...fragments.at(-1), quote: fragments.at(-1)!.exact, block_id: fragments.at(-1)!.block_id || anchor.block_id })
    if (!start || !end) return null
    const range = document.createRange(); range.setStart(start.startContainer, start.startOffset); range.setEnd(end.endContainer, end.endOffset); return range
  }
  const block = blockFromId(root, anchor.block_id)
  return block ? rangeInBlock(block, anchor) : null
}
