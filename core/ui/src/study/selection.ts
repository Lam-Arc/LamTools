/** Pure Unicode selection helpers shared by Study marks and tests. */
export interface SelectionRange { start: number; end: number }
export interface QuoteAnchor extends SelectionRange { exact: string; prefix: string; suffix: string }

function bounds(value: number, max: number): void {
  if (!Number.isInteger(value) || value < 0 || value > max) throw new Error('INVALID_OFFSET')
}

export function codePointToUtf16(text: string, point: number): number {
  const points = Array.from(text)
  bounds(point, points.length)
  return points.slice(0, point).join('').length
}

export function utf16ToCodePoint(text: string, unit: number): number {
  bounds(unit, text.length)
  if (unit > 0 && unit < text.length) {
    const before = text.charCodeAt(unit - 1)
    const after = text.charCodeAt(unit)
    if (before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff) throw new Error('SPLIT_SURROGATE')
  }
  return Array.from(text.slice(0, unit)).length
}

export function expandEnglishWord(text: string, range: SelectionRange): SelectionRange {
  const startUnit = codePointToUtf16(text, range.start)
  const endUnit = codePointToUtf16(text, range.end)
  if (endUnit <= startUnit) throw new Error('EMPTY_SELECTION')
  if (typeof Intl.Segmenter !== 'function') return range
  const segments = new Intl.Segmenter('en', { granularity: 'word' }).segment(text)
  for (const segment of segments) {
    const end = segment.index + segment.segment.length
    if (segment.isWordLike && startUnit >= segment.index && endUnit <= end && /^[A-Za-z]+(?:['’][A-Za-z]+)*$/.test(segment.segment)) {
      return { start: utf16ToCodePoint(text, segment.index), end: utf16ToCodePoint(text, end) }
    }
  }
  return range
}

export function makeAnchor(text: string, range: SelectionRange, contextPoints = 16): QuoteAnchor {
  const points = Array.from(text)
  bounds(range.start, points.length)
  bounds(range.end, points.length)
  if (range.end <= range.start || !Number.isInteger(contextPoints) || contextPoints < 0) throw new Error('INVALID_RANGE')
  return {
    ...range,
    exact: points.slice(range.start, range.end).join(''),
    prefix: points.slice(Math.max(0, range.start - contextPoints), range.start).join(''),
    suffix: points.slice(range.end, range.end + contextPoints).join(''),
  }
}

export function resolveQuote(anchor: QuoteAnchor, text: string, sameRevision: boolean): SelectionRange | null {
  if (!Number.isInteger(anchor.start) || !Number.isInteger(anchor.end) || !anchor.exact || anchor.start < 0 || anchor.end - anchor.start !== Array.from(anchor.exact).length) throw new Error('INVALID_ANCHOR')
  const points = Array.from(text)
  if (sameRevision && points.slice(anchor.start, anchor.end).join('') === anchor.exact) return { start: anchor.start, end: anchor.end }
  const matches: SelectionRange[] = []
  let offset = 0
  while (offset <= text.length) {
    const index = text.indexOf(anchor.exact, offset)
    if (index < 0) break
    const end = index + anchor.exact.length
    if ((!anchor.prefix || text.slice(Math.max(0, index - anchor.prefix.length), index) === anchor.prefix)
      && (!anchor.suffix || text.slice(end, end + anchor.suffix.length) === anchor.suffix)) {
      matches.push({ start: utf16ToCodePoint(text, index), end: utf16ToCodePoint(text, end) })
    }
    offset = index + 1
  }
  return matches.length === 1 ? matches[0] : null
}

