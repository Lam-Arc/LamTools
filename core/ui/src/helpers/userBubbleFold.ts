/**
 * user:“令用户气泡过长时自动折叠”+(超长用户消息默认收起，判定必须是纯函数：
 * 不依赖布局测量，测试与服务端预渲染都能得到同一结果)。
 */

/** 折叠阈值（估算行数）：估算超过该行数才折叠，恰好 8 行保持完整。 */
export const USER_BUBBLE_FOLD_LINES = 8

/** 折叠态保留的预览行数（展示层用 -webkit-line-clamp 裁剪）。 */
export const USER_BUBBLE_FOLDED_PREVIEW_LINES = 6

/**
 * 气泡一行可容纳的宽度单位。气泡内宽约 592px（min(72%, 620px) 减内边距），
 * 14px 字号下半角字符约 7px、CJK 满宽 14px，折算约 84 单位/行。
 */
const LINE_WIDTH_UNITS = 84

function textWidthUnits(line: string): number {
  let width = 0
  for (const ch of line) width += ch.charCodeAt(0) > 0xff ? 2 : 1
  return width
}

/** 按硬换行与超宽折行估算气泡的显示行数。 */
export function estimateUserBubbleLines(text: string): number {
  if (!text) return 0
  let lines = 0
  for (const line of String(text).split('\n')) {
    lines += Math.max(1, Math.ceil(textWidthUnits(line) / LINE_WIDTH_UNITS))
  }
  return lines
}

/** 是否长到值得折叠。 */
export function userBubbleShouldFold(text: string): boolean {
  return estimateUserBubbleLines(text) > USER_BUBBLE_FOLD_LINES
}
