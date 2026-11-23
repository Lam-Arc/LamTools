/**
 * 标注的数据模型（唯一一份）。
 *
 * user:“支持修改标注（可以复用ping的框选那里的标注功能与样式，将这一个功能抽出来共用）如箭头/文字等”+
 * (Ping 的截图编辑器和灯箱里的图片查看器共用这一份模型：工具种类、默认色、色板都放在这里，
 *  两边不再各写一套，避免改一处漏一处。)
 *
 * 坐标单位是「图片自身像素、左上原点」：宿主负责把屏幕坐标换算进图片坐标，
 * 绘制与导出也只认这一套，所以同一份标注在 100% 与放大后看起来是同一个位置。
 */

/** 能画在图片上的标记种类（`region` 是 Ping 的框选，不属于标注）。 */
export type AnnotationTool = 'arrow' | 'pen' | 'question' | 'exclamation' | 'text'

/** 图片坐标里的一个点。 */
export interface AnnotationPoint {
  x: number
  y: number
}

/**
 * 一条标注。
 *
 * 刻意保持极简（与 Ping 原模型一致）：没有单独的字号/线宽字段，
 * 大小由图片宽度推导（见 `draw.ts` 的 `annotationSize`），因此缩放图片不会让标注变形。
 */
export interface Annotation {
  id: number
  tool: AnnotationTool
  points: AnnotationPoint[]
  text?: string
  color: string
}

/** 每种工具的默认颜色：不问用户就先给一个能看清的色。 */
export const ANNOTATION_TOOL_COLORS: Record<AnnotationTool, string> = {
  question: '#6AA8FF',
  exclamation: '#FF9F5A',
  text: '#F4F7FF',
  arrow: '#FF6F91',
  pen: '#7ED6A5',
}

/** user:“给一些常见的颜色…这些颜色用圆形”+(色板共用一个顺序，两个宿主点出来的颜色一致)。 */
export const ANNOTATION_PALETTE: readonly string[] = [
  '#FF6F91', '#FF9F5A', '#FFD166', '#7ED6A5',
  '#6AA8FF', '#C7A6FF', '#F4F7FF', '#111318',
]

/** 当前该用哪个颜色：用户选过就用选的，否则用工具默认色。 */
export function annotationColor(tool: AnnotationTool, picked: string | null | undefined): string {
  return picked || ANNOTATION_TOOL_COLORS[tool] || '#ffffff'
}

/** 新建一条标注（只有起点；拖拽过程由宿主不断补点）。 */
export function createAnnotation(id: number, tool: AnnotationTool, start: AnnotationPoint, color: string): Annotation {
  return { id, tool, points: [start], color }
}
