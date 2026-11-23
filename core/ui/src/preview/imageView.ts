/**
 * 图片查看器的坐标与缩放（纯函数）。
 *
 * user:“灯箱应该配套缩放UI，支持Ctrl滚轮…默认大小自适应，左键可拖动”+
 * (视口坐标 = 容器里的 CSS 像素；图片坐标 = 图片自身像素。所有缩放/拖动都只改
 *  `{scale, x, y}` 这三个数，因此可以脱离 DOM 单测，也能保证指针落点与画布对齐)。
 *
 * `x` / `y` 是图片左上角在视口里的位置（像素），`scale` 是「一个图片像素占几个视口像素」。
 */

export interface ViewSize {
  width: number
  height: number
}

export interface ViewPoint {
  x: number
  y: number
}

export interface ImageView {
  scale: number
  x: number
  y: number
}

/** 缩放下限/上限：下限允许把大图整体缩到很小，上限不至于一步放大到糊。 */
export const IMAGE_MIN_SCALE = 0.02
export const IMAGE_MAX_SCALE = 8

export function clampScale(scale: number, min = IMAGE_MIN_SCALE, max = IMAGE_MAX_SCALE): number {
  if (!Number.isFinite(scale) || scale <= 0) return min
  return Math.min(max, Math.max(min, scale))
}

/**
 * 自适应缩放：大图缩到装得下，小图保持 1:1（不把 64px 的图标拉成一整屏）。
 *
 * 这正是原来灯箱里 Chromium 自带图片查看器的行为，换成自绘之后要保持一致。
 */
export function fitScale(image: ViewSize, viewport: ViewSize): number {
  if (!image.width || !image.height || !viewport.width || !viewport.height) return 1
  return clampScale(Math.min(1, viewport.width / image.width, viewport.height / image.height))
}

/** 把缩放后的图片摆在视口正中。 */
export function centeredView(image: ViewSize, viewport: ViewSize, scale: number): ImageView {
  const width = image.width * scale
  const height = image.height * scale
  return { scale, x: (viewport.width - width) / 2, y: (viewport.height - height) / 2 }
}

/**
 * 限制平移范围：装得下就居中（不允许拖出边框），装不下才允许拖，且边缘不越过视口。
 *
 * user:“左键可拖动”+(拖动只改位置，不改缩放；到边就停，不用橡皮筋回弹)。
 */
export function clampView(view: ImageView, image: ViewSize, viewport: ViewSize): ImageView {
  const width = image.width * view.scale
  const height = image.height * view.scale
  const x = width <= viewport.width
    ? (viewport.width - width) / 2
    : Math.min(0, Math.max(viewport.width - width, view.x))
  const y = height <= viewport.height
    ? (viewport.height - height) / 2
    : Math.min(0, Math.max(viewport.height - height, view.y))
  return { scale: view.scale, x, y }
}

/** 视口坐标 → 图片坐标（指针落点换算）。 */
export function screenToImage(view: ImageView, point: ViewPoint): ViewPoint {
  return { x: (point.x - view.x) / view.scale, y: (point.y - view.y) / view.scale }
}

/** 图片坐标 → 视口坐标（文字输入框要贴着点击位置显示）。 */
export function imageToScreen(view: ImageView, point: ViewPoint): ViewPoint {
  return { x: point.x * view.scale + view.x, y: point.y * view.scale + view.y }
}

/**
 * 以某个视口点为锚缩放：锚点下面的那块图不动。
 *
 * user:“支持Ctrl滚轮”+(滚轮缩放要跟手：光标指哪，放大后那里还在光标下)。
 */
export function scaleAt(view: ImageView, image: ViewSize, viewport: ViewSize, nextScale: number, anchor: ViewPoint): ImageView {
  const scale = clampScale(nextScale)
  const imagePoint = screenToImage(view, anchor)
  return clampView({
    scale,
    x: anchor.x - imagePoint.x * scale,
    y: anchor.y - imagePoint.y * scale,
  }, image, viewport)
}

/** 以视口中心为锚点缩放（工具栏的 +/− 与键盘用它）。 */
export function zoomAtCenter(view: ImageView, image: ViewSize, viewport: ViewSize, factor: number): ImageView {
  return scaleAt(view, image, viewport, view.scale * factor, { x: viewport.width / 2, y: viewport.height / 2 })
}
