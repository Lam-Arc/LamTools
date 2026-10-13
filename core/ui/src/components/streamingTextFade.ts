interface FadeRange {
  start: number
  end: number
  startedAt: number
}

export interface StreamingTextFade {
  text: string
  ranges: FadeRange[]
}

// Matches --dur-base. Only recent ranges survive tail rebuilds; there is no
// animation timer or work on previously closed segments.
const FADE_DURATION_MS = 180

export function fadeStreamingText(
  nodes: ChildNode[],
  previous: StreamingTextFade | undefined,
  animate: boolean,
  now = Date.now(),
): StreamingTextFade {
  const texts: Text[] = []
  for (const root of nodes) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    let node: Node | null
    while ((node = walker.nextNode())) {
      // Keep controls and generated math/SVG untouched. Root whitespace is
      // structural, and must not shift the offsets of visible prose.
      const parent = node.parentElement
      if (!parent || !node.textContent?.trim()
        || parent.closest('button, .katex, svg, math, style, script')) continue
      texts.push(node as Text)
    }
  }
  const text = texts.map(node => node.data).join('')
  let prefix = 0
  if (previous) {
    while (prefix < text.length && prefix < previous.text.length
      && text[prefix] === previous.text[prefix]) prefix += 1
    // Do not split a surrogate pair across animation spans.
    if (prefix > 0 && /[\uD800-\uDBFF]/.test(text[prefix - 1])) prefix -= 1
  }
  const ranges = animate
    ? (previous?.ranges ?? [])
      .filter(range => range.start < prefix && now - range.startedAt < FADE_DURATION_MS)
      .map(range => ({ ...range, end: Math.min(range.end, prefix) }))
    : []
  if (animate && prefix < text.length) ranges.push({ start: prefix, end: text.length, startedAt: now })

  let offset = 0
  for (const node of texts) {
    const end = offset + node.length
    const overlaps = ranges.filter(range => range.start < end && range.end > offset)
    if (overlaps.length) {
      const fragment = document.createDocumentFragment()
      let cursor = 0
      for (const range of overlaps) {
        const start = Math.max(range.start - offset, 0)
        const stop = Math.min(range.end - offset, node.length)
        fragment.append(node.data.slice(cursor, start))
        const revealed = node.data.slice(start, stop)
        if (revealed.trim()) {
          const span = document.createElement('span')
          span.className = 'stream-text-fade'
          span.style.setProperty('--stream-fade-age', `${now - range.startedAt}ms`)
          span.textContent = revealed
          fragment.append(span)
        } else fragment.append(revealed)
        cursor = stop
      }
      fragment.append(node.data.slice(cursor))
      node.replaceWith(fragment)
    }
    offset = end
  }
  return { text, ranges }
}
