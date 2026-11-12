/**
 * 瞬时标记的时间计算：寿命、淡出、弹幕位移、表情包回弹、SVG 逐段描边。
 *
 * user:“这个东西最主要的是交互体验…弹幕从右飘到左，表情包，受控时长。
 * 表情包标记的是 3 秒，我传的参数就是 3 秒，发出去 3 秒钟之后自动淡出消失”+
 * (所有动画都由时间推出来，不靠 CSS 生命周期猜；同一份状态在任何时候重画，
 *  都能落在正确的进度上。)
 */
import type { MarkDraw, OverlayMark, SvgShape } from './model.ts'

export function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

/** 进入、停留、淡出的透明度。ttl 到点就是 0。 */
export function lifeOpacity(mark: OverlayMark, now: number): number {
  const ttl = Math.max(0.1, mark.ttl || 0.1)
  const age = now - mark.created_at
  if (age <= 0) return 0
  if (age >= ttl) return 0
  const enter = Math.min(0.18, ttl * 0.2)
  const fade = Math.min(mark.motion?.fade ?? 0.3, ttl * 0.9)
  if (age < enter) return clamp01(age / enter)
  if (fade > 0 && age > ttl - fade) return clamp01((ttl - age) / fade)
  return 1
}

/** 进入动画的进度，0 开始，1 结束。弹幕默认占满整个寿命。 */
export function motionProgress(mark: OverlayMark, now: number): number {
  const duration = Math.max(0.05, mark.motion?.duration ?? mark.ttl ?? 0.05)
  return clamp01((now - mark.created_at) / duration)
}

/** 弹幕横向进度，组件据此决定从右往左还是反过来。 */
export function danmakuProgress(mark: OverlayMark, now: number): number {
  return motionProgress(mark, now)
}

/** 表情包的回弹缩放：从 0 弹到 1，略过冲再回落。 */
export function stickerPopScale(mark: OverlayMark, now: number): number {
  const progress = motionProgress(mark, now)
  const c1 = 1.70158
  const c3 = c1 + 1
  const shifted = progress - 1
  return 1 + c3 * shifted * shifted * shifted + c1 * shifted * shifted
}

/**
 * 单个 SVG 图形的描边进度。
 *
 * user:“不用专门分段，而是做流式渲染”+(每个图形从它到达那一刻开始画，
 * 后追加的图形接着画；不预先排队，也不整批延迟)。
 */
export function shapeProgress(shape: SvgShape, draw: MarkDraw | undefined, now: number): number {
  if (!draw || draw.mode === 'none') return 1
  const duration = Math.max(0.05, draw.duration)
  const added = shape.added_at ?? 0
  return clamp01((now - added) / duration)
}

export interface StrokeStyle {
  pathLength?: number
  strokeDasharray?: string
  strokeDashoffset?: number
  fillOpacity?: number
}

/**
 * 描边模式下的样式：用 `pathLength=1` 把任意长度的路径归一化，
 * 不依赖 getTotalLength，也不会因为路径很长而画得断断续续。
 */
export function strokeStyle(
  shape: SvgShape,
  draw: MarkDraw | undefined,
  now: number,
  baseFillOpacity = 1,
): StrokeStyle {
  if (!draw || draw.mode === 'none') return { fillOpacity: baseFillOpacity }
  const progress = shapeProgress(shape, draw, now)
  if (draw.mode === 'reveal') {
    return { fillOpacity: progress * baseFillOpacity }
  }
  return {
    pathLength: 1,
    strokeDasharray: '1',
    strokeDashoffset: 1 - progress,
    // 填充跟着描边一起长出来，避免先看到一整块色。
    fillOpacity: progress * baseFillOpacity,
  }
}
// ---------------------------------------------------------------------------
// 弹幕：只在上方 30% 区域飘，越长越慢，速度可按倍速放大
// ---------------------------------------------------------------------------

export interface DanmakuSettings {
  /** 全局倍速，1 是默认。 */
  speed: number
  fontFamily: string
  fontSize: number
}

export const DEFAULT_DANMAKU_SETTINGS: DanmakuSettings = {
  speed: 1,
  fontFamily: '',
  fontSize: 24,
}

/** user:“弹幕位置调整一下，30%上方屏幕”+(只在屏幕上方这条带子里排轨道)。 */
export const DANMAKU_BAND_RATIO = 0.3

/**
 * 轨道起始留白：工具条是贴屏幕上沿的胶囊，弹幕不该从它下面穿过去。
 *
 * user:“上方那个条和电脑使用时候的样式用同一个”+(胶囊贴到 y=0 之后会盖住
 * 最早那条轨道，轨道整体下移到胶囊下方)。
 */
export const DANMAKU_TOP_INSET = 44

export interface DanmakuLayout {
  /** 轨道顶边（页面 CSS 像素）。 */
  top: number
  /** 整条弹幕的估算宽度，用来算起止位置。 */
  width: number
  /** 从进场到离场的总时长，秒。 */
  duration: number
  fromLeft: boolean
}

/** 中日韩字符按一个字号宽，西文数字按 0.58 个字号宽估算。 */
export function estimateTextWidth(text: string, fontSize: number): number {
  let width = 0
  for (const char of text) {
    width += /[⺀-￿]/.test(char) ? fontSize : fontSize * 0.58
  }
  return Math.max(fontSize * 1.6, width + 16)
}

/**
 * 弹幕速度：字越多越慢。
 *
 * user:“速度根据长度调整快慢，越长越慢”+(短句快速掠过，长句放慢让人看得完；
 * 倍速只整体缩放，不改变“长句更慢”这个相对关系)。
 */
export function danmakuSpeed(text: string, fontSize: number, speed = 1, widthOverride?: number): number {
  // 图片弹幕的长度由图片宽度决定，不能只拿文字去估，否则长短和速度脱钩。
  const width = widthOverride && widthOverride > 0 ? widthOverride : estimateTextWidth(text, fontSize)
  const base = 240
  const extra = Math.max(0, width - fontSize * 5)
  // 每多 26 个字号的宽度，速度最多再降 55%。
  const slowdown = Math.min(0.55, extra / (fontSize * 26))
  return Math.max(40, base * Math.max(0.2, speed) * (1 - slowdown))
}

/** 屏幕几何：高度要分物理和 CSS 两套，锚点是物理像素，轨道在 CSS 像素里排。 */
export interface DanmakuViewport {
  cssHeight: number
  physicalHeight: number
}

/** 轨道行距：正文行高再加一道缝。
 *
 * user:“弹幕流畅一点，不要一顿一顿地飘”“弹幕位置调整一下，30%上方屏幕”+
 * (同一批弹幕的锚点常常只差几十个物理像素，按整屏比例摊到 30% 带子里只剩
 *  十几像素，20px 字号直接叠字；轨道必须按字高对齐成行。)
 */
export function danmakuTrackPitch(fontSize: number): number {
  return Math.max(16, fontSize * 1.6) + 8
}

/** 弹幕在屏幕上的位置、宽度和时长。 */
export function danmakuLayout(
  mark: OverlayMark,
  viewport: DanmakuViewport,
  viewportWidth: number,
  settings: DanmakuSettings,
): DanmakuLayout {
  const fontSize = Math.max(12, settings.fontSize)
  const width = mark.image?.width ?? estimateTextWidth(mark.text || '', fontSize)
  const lineHeight = fontSize * 1.6
  const band = viewport.cssHeight * DANMAKU_BAND_RATIO
  const physicalHeight = viewport.physicalHeight > 0 ? viewport.physicalHeight : viewport.cssHeight
  // 锚点是屏幕物理像素，轨道排在页面 CSS 像素里，先换算再对齐成行。
  const ratio = physicalHeight > 0 ? viewport.cssHeight / physicalHeight : 1
  const anchorCss = Math.max(0, (mark.points[0]?.[1] ?? 0) * ratio)
  const pitch = danmakuTrackPitch(fontSize)
  const maxTop = Math.max(DANMAKU_TOP_INSET, band - lineHeight)
  const maxTrack = Math.max(0, Math.floor((maxTop - DANMAKU_TOP_INSET) / pitch))
  const track = Math.min(maxTrack, Math.max(0, Math.round((anchorCss - DANMAKU_TOP_INSET) / pitch)))
  const top = Math.min(maxTop, DANMAKU_TOP_INSET + track * pitch)
  const speed = danmakuSpeed(mark.text || '', fontSize, settings.speed, width)
  const distance = viewportWidth + width
  const crossing = distance / Math.max(20, speed)
  // user:“让它们流畅一些”“速度根据长度调整快慢”+(位移要在这个标记的寿命里走完：
  // ttl 短于跨屏时间时按寿命反推，宁可快一点，也不能飘到一半被抹掉)。
  const life = Math.max(0.6, (mark.ttl || 0.6) - 0.05)
  const duration = Math.min(Math.max(1.2, crossing), life)
  return { top, width, duration, fromLeft: mark.motion?.from === 'left' }
}
