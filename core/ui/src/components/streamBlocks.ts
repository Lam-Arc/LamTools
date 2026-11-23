/**
 * 流式「块级落定」：文字立即落地，只给**刚写完的一块**做一次短动画。
 *
 * user:“做C”+(不做打字机、不做逐字 span。文字照旧立刻出现在 DOM 里；
 *  只有内容里“出现了一个换行/一块写完”的那一刻，才把这一块新文字包一层 180ms 淡入。
 *  chunk 慢的时候不会一顿一顿地跳半句，chunk 快的时候也不会叠出成百上千个动画节点。)
 *
 * 为什么按**源文本的换行**判断，而不是按 DOM 里的换行：
 * markdown 渲染会把段落内的换行吃掉（DOM 文本里根本没有 `\n`），
 * 所以“这一块写完了没有”只能看源文本；DOM 只负责把对应的一段包起来。
 */

/** 超长消息不做块动画：包裹与重排都不值得，宁可静态。 */
const MAX_ANIMATED_TEXT = 200_000
const EXCLUDED_TEXT = 'button, .katex, svg, math, style, script'

/** 源文本里，`from` 之后最后一个换行的位置；没有就返回 -1。 */
export function lastNewlineFrom(text: string, from: number): number {
  const index = text.lastIndexOf('\n')
  return index >= from ? index : -1
}

/**
 * 把「从 `from` 之后新出现的可见文字」整段包一次动画，返回新的已动画字符数。
 * 只在“源文本出现了新换行”时调用；重复调用不会重放已动画的部分。
 */
export function markBlockEnter(container: HTMLElement, from: number): number {
  if (!container) return from
  // 先回收上一次的动画节点：闭合段会复用旧 DOM，不回收的话 span 会一段段累积。
  for (const span of Array.from(container.querySelectorAll('span.stream-block-enter'))) {
    span.replaceWith(...Array.from(span.childNodes))
  }
  // user:“优化完继续track，找到下一个最大卡顿点，然后修复”+
  // (一次遍历只保留新文字的范围，普通段落不逐个查询排除项的祖先)。
  if (container.closest(EXCLUDED_TEXT)) return from
  const hasExcludedText = container.querySelector(EXCLUDED_TEXT) !== null
  const document = container.ownerDocument
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  const additions: Array<{ node: Text; offset: number }> = []
  let length = 0
  for (let node = walker.nextNode() as Text | null; node; node = walker.nextNode() as Text | null) {
    if (!node.data.trim() || (hasExcludedText && node.parentElement?.closest(EXCLUDED_TEXT))) continue
    const end = length + node.length
    if (end > from && end <= MAX_ANIMATED_TEXT) {
      additions.push({ node, offset: Math.max(from - length, 0) })
    }
    length = end
  }
  if (length > MAX_ANIMATED_TEXT) return length
  if (length <= from) return from
  for (const { node, offset } of additions) {
    const range = document.createRange()
    range.setStart(node, offset)
    range.setEnd(node, node.length)
    const span = document.createElement('span')
    span.className = 'stream-block-enter'
    range.surroundContents(span)
  }
  return length
}
