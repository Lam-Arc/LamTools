/**
 * 三级间距标注。
 *
 * user:“间距充足：朝上的横向大括号，数值在外侧；较小间距：简化为 >；极小间距：只留单段折线。
 * 标注根据缩放后的可见尺寸选择等级；标签始终在间距外面；即便实际 gap 为 0–2px，
 * 点击热区和数字仍保持屏幕级最小尺寸”+
 * (几何判定与路径生成只做纯计算，画布负责渲染与交互。)
 */

export type GapLevel = 'brace' | 'chevron' | 'segment'

export interface AnnotationRect {
  left: number
  top: number
  width: number
  height: number
}

export interface GapBand {
  /** 间距带：相邻两元素之间的区域（屏幕坐标）。 */
  band: AnnotationRect
  /** 竖向排列（上下相邻）或横向排列（左右相邻）。 */
  axis: 'vertical' | 'horizontal'
  /** 可见间距（CSS px）。 */
  gap: number
  /** 画布缩放；热区与标签按它换算，保持屏幕尺寸。 */
  scale?: number
}

export interface GapAnnotation {
  level: GapLevel
  /** SVG path，坐标是画布本地坐标。 */
  path: string
  /** 标签位置与外锚点。 */
  label: { x: number; y: number; anchor: 'start' | 'middle' | 'end' }
  /** 交互热区，至少 24×18 屏幕像素。 */
  hit: AnnotationRect
}

/** 两档阈值按可见尺寸定：≥12px 画括号，≥4px 画 >，更小只留一段线。 */
export const GAP_BRACE_MIN = 12
export const GAP_CHEVRON_MIN = 4
/** 热区屏幕尺寸下限。 */
export const GAP_HIT_MIN_WIDTH = 24
export const GAP_HIT_MIN_HEIGHT = 18

export function chooseGapLevel(gap: number): GapLevel {
  if (gap >= GAP_BRACE_MIN) return 'brace'
  if (gap >= GAP_CHEVRON_MIN) return 'chevron'
  return 'segment'
}

function round(value: number): number {
  return Math.round(value * 10) / 10
}

function minSize(value: number, scale: number): number {
  return value / Math.max(0.1, scale)
}

/**
 * 从相邻两元素推出间距带。
 * 两个方向都重叠时返回 null（没有可标注的间距）。
 */
export function measureGap(previous: AnnotationRect, current: AnnotationRect): GapBand | null {
  const vertical = current.top - (previous.top + previous.height)
  const horizontal = current.left - (previous.left + previous.width)
  if (vertical <= 0 && horizontal <= 0) return null
  if (vertical >= horizontal) {
    const left = Math.max(previous.left, current.left)
    const right = Math.min(previous.left + previous.width, current.left + current.width)
    const width = Math.max(0, right - left)
    return {
      axis: 'vertical',
      gap: vertical,
      band: {
        left: width > 0 ? left : Math.min(previous.left, current.left),
        top: previous.top + previous.height,
        width: width > 0 ? width : Math.max(previous.width, current.width),
        height: vertical,
      },
    }
  }
  const top = Math.max(previous.top, current.top)
  const bottom = Math.min(previous.top + previous.height, current.top + current.height)
  const height = Math.max(0, bottom - top)
  return {
    axis: 'horizontal',
    gap: horizontal,
    band: {
      left: previous.left + previous.width,
      top: height > 0 ? top : Math.min(previous.top, current.top),
      width: horizontal,
      height: height > 0 ? height : Math.max(previous.height, current.height),
    },
  }
}

/** 生成标注：路径、标签、热区。 */
export function buildGapAnnotation(input: GapBand): GapAnnotation {
  const scale = input.scale ?? 1
  const { band, axis, gap } = input
  const level = chooseGapLevel(gap)
  const centerX = band.left + band.width / 2
  const centerY = band.top + band.height / 2
  const arm = minSize(6, scale)

  let path = ''
  if (axis === 'vertical') {
    if (level === 'brace') {
      // 朝上的横向大括号：两端竖臂 + 中间小尖，整体在间距带里。
      const top = band.top + band.height * 0.18
      const bottom = band.top + band.height * 0.82
      path = [
        `M ${round(band.left)} ${round(bottom)}`,
        `L ${round(band.left)} ${round(top)}`,
        `L ${round(centerX - arm)} ${round(top)}`,
        `L ${round(centerX)} ${round(top + arm)}`,
        `L ${round(centerX + arm)} ${round(top)}`,
        `L ${round(band.left + band.width)} ${round(top)}`,
        `L ${round(band.left + band.width)} ${round(bottom)}`,
      ].join(' ')
    } else if (level === 'chevron') {
      path = [
        `M ${round(centerX - arm)} ${round(centerY - arm)}`,
        `L ${round(centerX + arm)} ${round(centerY)}`,
        `L ${round(centerX - arm)} ${round(centerY + arm)}`,
      ].join(' ')
    } else {
      path = `M ${round(band.left)} ${round(centerY)} L ${round(band.left + band.width)} ${round(centerY)}`
    }
  } else {
    if (level === 'brace') {
      const left = band.left + band.width * 0.18
      const right = band.left + band.width * 0.82
      path = [
        `M ${round(right)} ${round(band.top)}`,
        `L ${round(left)} ${round(band.top)}`,
        `L ${round(left)} ${round(centerY - arm)}`,
        `L ${round(left + arm)} ${round(centerY)}`,
        `L ${round(left)} ${round(centerY + arm)}`,
        `L ${round(left)} ${round(band.top + band.height)}`,
        `L ${round(right)} ${round(band.top + band.height)}`,
      ].join(' ')
    } else if (level === 'chevron') {
      path = [
        `M ${round(centerX - arm)} ${round(centerY - arm)}`,
        `L ${round(centerX + arm)} ${round(centerY)}`,
        `L ${round(centerX - arm)} ${round(centerY + arm)}`,
      ].join(' ')
    } else {
      path = `M ${round(centerX)} ${round(band.top)} L ${round(centerX)} ${round(band.top + band.height)}`
    }
  }

  // 标签永远在间距带外面：优先上/右，位置不够时换下/左。
  let label: GapAnnotation['label']
  if (axis === 'vertical') {
    const above = band.top - minSize(8, scale)
    label = above > minSize(14, scale)
      ? { x: centerX, y: above, anchor: 'middle' }
      : { x: centerX, y: band.top + band.height + minSize(16, scale), anchor: 'middle' }
  } else {
    const right = band.left + band.width + minSize(8, scale)
    label = { x: right, y: centerY, anchor: 'start' }
  }

  const hitWidth = Math.max(band.width, minSize(GAP_HIT_MIN_WIDTH, scale))
  const hitHeight = Math.max(band.height, minSize(GAP_HIT_MIN_HEIGHT, scale))
  const hit: AnnotationRect = axis === 'vertical'
    ? {
        left: centerX - hitWidth / 2,
        top: centerY - hitHeight / 2,
        width: hitWidth,
        height: hitHeight,
      }
    : {
        left: centerX - hitWidth / 2,
        top: centerY - hitHeight / 2,
        width: hitWidth,
        height: hitHeight,
      }

  return { level, path, label, hit }
}

/** 标注等级的说明，给属性面板或提示用。 */
export function gapLevelLabel(level: GapLevel): string {
  return level === 'brace' ? '大括号' : level === 'chevron' ? '折角' : '线段'
}
