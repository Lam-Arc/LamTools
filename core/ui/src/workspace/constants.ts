/**
 * 工作区尺寸常量（唯一来源）。
 *
 * user:“落点矩形必须满足不变量：完全落在所属 pane 的内容区内（不含标签栏、不含页眉）”+
 * (标签条与页眉的高度是几何计算的输入，必须有唯一来源：之前它们散在 layout.ts / 组件 / 测试里，
 *  迁移时丢一个就会让 contentRect 算成 NaN，网页直接不显示)。
 */
export const SPLIT_TAB_BAR_HEIGHT = 36
export const WORKSPACE_HEADER_HEIGHT = 36
