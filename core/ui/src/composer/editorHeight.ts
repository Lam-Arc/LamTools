/**
 * Height cap for the main composer editor.
 *
 * The editor grows with its content until the cap, then scrolls inside the
 * capped box instead of stretching the composer card any further.
 */

// user:“修复输入栏高度无上限的 bug，多行时可达 8 行高即为极限”+(主输入栏
// 编辑器最多长到 8 行文字的高度，再多就在框内滚动)。
export const COMPOSER_EDITOR_MAX_LINES = 8

/** Matches the `.cm-content` vertical padding set in the same editor theme. */
export const COMPOSER_EDITOR_CONTENT_PADDING = '8px'

/**
 * Height that fits exactly `COMPOSER_EDITOR_MAX_LINES` content lines:
 * lines × line-height plus the top and bottom content padding.
 */
export function composerEditorMaxHeight(
  lineHeight = '1.6em',
  contentPadding = COMPOSER_EDITOR_CONTENT_PADDING,
): string {
  return `calc(${COMPOSER_EDITOR_MAX_LINES} * ${lineHeight} + 2 * ${contentPadding})`
}
