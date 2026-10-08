/**
 * Growing text field: the markup's `rows` gives the resting height, and the
 * field grows with its content until `maxRows` lines, then scrolls inside that
 * cap instead of clipping the answer.
 */
export const TEXTAREA_MAX_ROWS = 5

export function autoGrowTextarea(
  element: HTMLTextAreaElement | null | undefined,
  maxRows: number = TEXTAREA_MAX_ROWS,
): void {
  if (!element) return
  const style = window.getComputedStyle(element)
  const lineHeight = Number.parseFloat(style.lineHeight) || 20
  const padding = (Number.parseFloat(style.paddingTop) || 0) + (Number.parseFloat(style.paddingBottom) || 0)
  const cap = lineHeight * maxRows + padding

  // Height must be released before reading the content, otherwise a shrunk
  // answer keeps the box at its previous height.
  element.style.height = 'auto'
  const contentHeight = element.scrollHeight
  element.style.height = `${Math.min(contentHeight, cap)}px`
  element.style.overflowY = contentHeight > cap ? 'auto' : 'hidden'
}
