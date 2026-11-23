/**
 * 输入栏所在的「主内容列」几何。
 *
 * user:“输入栏跨出了主区——那条输入栏从聊天区一直横跨到右侧分屏上方，压住了打开内容/辅助对话按钮”+
 * (输入栏是 position:fixed、靠 --composer-anchor-left / --composer-full-width 定位的；
 *  分屏时这两个变量由 --split-primary-x/-width 拼出来，一旦那些变量缺失，
 *  calc() 整条失效 → width/left 退化成 auto，就会横跨到分屏上方。
 *  这里把「主内容列」与「输入栏矩形」写成纯函数：列变了、窄窗了，都能先算出来再断言)。
 */

export interface Box { x: number; y: number; width: number; height: number }

/** 输入栏的最小可用宽度（再窄就没法打字了）。 */
export const COMPOSER_MIN_WIDTH = 240

/**
 * 主内容列：分屏时就是主 pane（`mainPane`），没分屏时就是主区（`mainRegion`）。
 * 只取横向信息，纵向由 CSS 自己决定。
 */
export function composerColumnBox(mainRegion: Box, mainPane: Box | null): Box {
  const source = mainPane && mainPane.width > 0 ? mainPane : mainRegion
  return { x: source.x, y: source.y, width: Math.max(0, source.width), height: Math.max(0, source.height) }
}

export interface ComposerBoxOptions {
  /** 列内左右各留多少（与 CSS 的 --space-5 对应）。 */
  padding?: number
  /** 内容栏上限（与 CSS 的 --content-fill-width 对应）。 */
  contentFill?: number
  /** 最小可用宽度。 */
  minWidth?: number
}

/**
 * user:“允许的最多是把「主区宽度 - 安全边距」；窗口很窄 / 分屏很宽时输入栏仍然可用（保持最小宽度、不被裁切）”+
 * (宽度 = 列宽 − 两侧内边距，再与内容栏上限取小；但永远不小于 minWidth —— 列真的比 minWidth 还窄时，
 *  宁可贴着列居中溢出一点，也不要把输入栏压成一条缝。)
 */
export function composerBoxFor(column: Box, options: ComposerBoxOptions = {}): Box {
  const padding = Math.max(0, options.padding ?? 24)
  const contentFill = options.contentFill ?? 1040
  const minWidth = Math.max(1, options.minWidth ?? COMPOSER_MIN_WIDTH)
  const available = Math.max(0, column.width - padding * 2)
  const width = Math.max(minWidth, Math.min(available, contentFill))
  const center = column.x + column.width / 2
  return { x: center - width / 2, y: column.y, width, height: column.height }
}

/** 输入栏是否完全落在主内容列里（左右各容许 0.5px 取整误差）。 */
export function composerInsideColumn(column: Box, composer: Box, epsilon = 0.5): boolean {
  return composer.x >= column.x - epsilon
    && composer.x + composer.width <= column.x + column.width + epsilon
}

/**
 * user:“若某些形态下主列几何变量缺失，就回退到「主区容器 getBoundingClientRect()」而不是 100vw——
 * 宽度绝不允许多于主列”+
 * (上一轮只把实测值写成 CSS 变量，还要跨两跳才生效：`.workspace-shell--split` 类命中 + 变量继承。
 *  任何一跳失配，`var()` 找不到就整条回退到 100vw，于是输入栏又横跨到分屏上。
 *  这里直接把结论算成**内联样式**：内联优先级最高，不需要选择器命中，也不可能被别的规则顶掉。
 *  宽度先按「列宽 − 两侧内边距」算，再与「列右缘硬上限」取小 —— 所以任何情况下都不会宽于主列。)
 */
export interface ComposerInlineStyle {
  /** 输入栏中心线（配合 CSS 的 `transform: translateX(-50%)`）。 */
  left: string
  width: string
  /** 右缘硬上限：即使最小宽度兜底生效，也不许超过主列。 */
  maxWidth: string
}

export function composerColumnStyle(
  column: Box,
  options: ComposerBoxOptions & { edge?: number } = {},
): ComposerInlineStyle {
  const box = composerBoxFor(column, options)
  // 列右缘与输入栏右缘之间至少留出的一点空气（与 CSS 的 --space-2 对应）。
  const edge = Math.max(0, options.edge ?? 8)
  const maxWidth = Math.max(0, column.width - edge * 2)
  const width = Math.min(box.width, maxWidth)
  return {
    left: `${Math.round(column.x + column.width / 2)}px`,
    width: `${Math.round(width)}px`,
    maxWidth: `${Math.round(maxWidth)}px`,
  }
}
