/**
 * 「聊天/工作」胶囊的三档降级（纯函数，便于单测）。
 *
 * user:“这个空间怎么看也不像会互相挤，肯定是哪里有问题”+
 * (胶囊所在的是空会话引导块 `.empty-session-hero`，不在输入栏那一行，本来就没有“和输入框抢宽度”这件事。
 *  所以判档不再按拍脑袋的 480/340，而是按**胶囊自己需要多宽**来算：
 *  空间够就保持原来的等宽两格，只有放不下时才收紧、再不行才收成一个按钮)。
 */
export type RunModeTier = 'full' | 'compact' | 'icon'

/** 一档需要的宽度：两格各 132px + 2px 缝 + 两侧各 4px 内边距 = 274px（这就是改造前的原样）。 */
export const RUN_MODE_TIER_FULL_MIN = 274
/** 二档需要的宽度：两格各 4em(56px) + 2px 缝 + 两侧各 4px 内边距 = 122px。 */
export const RUN_MODE_TIER_COMPACT_MIN = 122

/**
 * 按**可用宽度**分档。
 * - `<= 0` 表示还没量到布局（首次渲染前）：先按完整档显示，避免一上来闪成图标/按钮；
 * - 足够放下原来的两格 → `full`（视觉与改造前一致，不做任何压缩）；
 * - 放得下收紧的两格 → `compact`；
 * - 再窄 → `icon`（单个按钮 + 菜单）。
 */
export function runModeTier(availableWidth: number): RunModeTier {
  if (!Number.isFinite(availableWidth) || availableWidth <= 0) return 'full'
  if (availableWidth >= RUN_MODE_TIER_FULL_MIN) return 'full'
  if (availableWidth >= RUN_MODE_TIER_COMPACT_MIN) return 'compact'
  return 'icon'
}
