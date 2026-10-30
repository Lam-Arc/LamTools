/**
 * 头像裁切的坐标换算。
 *
 * user:“助手头像那块别填链接 上传，裁切”+(头像改成上传后手动裁切：
 * 预览框固定为正方形，图片按 cover 铺满并可拖动、缩放；导出时按同一份
 * 几何把框内看到的部分画进正方形画布)。
 *
 * 这里只放纯计算，不碰 DOM：组件负责事件与 canvas，测试直接验这层。
 */
export interface AvatarCropImageSize {
  width: number
  height: number
}

export interface AvatarCropOffset {
  x: number
  y: number
}

export interface AvatarCropRect {
  sx: number
  sy: number
  width: number
  height: number
}

/** 导出画布边长：界面头像最大显示 40px 左右，256 已足够清晰且体积可控。 */
export const ASSISTANT_AVATAR_EXPORT_SIZE = 256
export const ASSISTANT_AVATAR_MIN_ZOOM = 1
export const ASSISTANT_AVATAR_MAX_ZOOM = 4

function safeImageSize(image: AvatarCropImageSize): AvatarCropImageSize {
  return {
    width: Math.max(0, Number.isFinite(image.width) ? image.width : 0),
    height: Math.max(0, Number.isFinite(image.height) ? image.height : 0),
  }
}

/** cover 基准倍率：zoom=1 时图片刚好铺满正方形裁切框（短边对齐）。 */
export function avatarCoverScale(frameSize: number, image: AvatarCropImageSize): number {
  const size = safeImageSize(image)
  if (frameSize <= 0 || size.width <= 0 || size.height <= 0) return 0
  return Math.max(frameSize / size.width, frameSize / size.height)
}

/** 当前缩放下的图片显示尺寸（像素）。 */
export function avatarDisplaySize(
  frameSize: number,
  image: AvatarCropImageSize,
  zoom: number,
): AvatarCropImageSize {
  const scale = avatarCoverScale(frameSize, image) * Math.max(ASSISTANT_AVATAR_MIN_ZOOM, zoom)
  if (scale <= 0) return { width: 0, height: 0 }
  const size = safeImageSize(image)
  return { width: size.width * scale, height: size.height * scale }
}

/** 位置限制：图片必须始终盖住裁切框，不能拖出空白。 */
export function clampAvatarOffset(
  offset: AvatarCropOffset,
  frameSize: number,
  display: AvatarCropImageSize,
): AvatarCropOffset {
  const minX = Math.min(0, frameSize - display.width)
  const minY = Math.min(0, frameSize - display.height)
  return {
    x: Math.min(0, Math.max(minX, Number.isFinite(offset.x) ? offset.x : 0)),
    y: Math.min(0, Math.max(minY, Number.isFinite(offset.y) ? offset.y : 0)),
  }
}

/** 初始位置：图片居中。 */
export function centeredAvatarOffset(frameSize: number, display: AvatarCropImageSize): AvatarCropOffset {
  return clampAvatarOffset(
    { x: (frameSize - display.width) / 2, y: (frameSize - display.height) / 2 },
    frameSize,
    display,
  )
}

/** 缩放时保持裁切框中心对着的图片位置不变，避免一拉滑块画面乱跳。 */
export function rescaleAvatarOffset(
  frameSize: number,
  previousDisplay: AvatarCropImageSize,
  nextDisplay: AvatarCropImageSize,
  offset: AvatarCropOffset,
): AvatarCropOffset {
  if (previousDisplay.width <= 0 || previousDisplay.height <= 0) {
    return centeredAvatarOffset(frameSize, nextDisplay)
  }
  const centerX = (frameSize / 2 - offset.x) / previousDisplay.width
  const centerY = (frameSize / 2 - offset.y) / previousDisplay.height
  return clampAvatarOffset(
    { x: frameSize / 2 - centerX * nextDisplay.width, y: frameSize / 2 - centerY * nextDisplay.height },
    frameSize,
    nextDisplay,
  )
}

/** 框内可见区域对应的原图像素矩形，用于 canvas.drawImage。 */
export function avatarCropSourceRect(
  frameSize: number,
  image: AvatarCropImageSize,
  zoom: number,
  offset: AvatarCropOffset,
): AvatarCropRect {
  const size = safeImageSize(image)
  const scale = avatarCoverScale(frameSize, size) * Math.max(ASSISTANT_AVATAR_MIN_ZOOM, zoom)
  if (scale <= 0) return { sx: 0, sy: 0, width: 0, height: 0 }
  const viewWidth = Math.min(size.width, frameSize / scale)
  const viewHeight = Math.min(size.height, frameSize / scale)
  const maxSx = Math.max(0, size.width - viewWidth)
  const maxSy = Math.max(0, size.height - viewHeight)
  return {
    sx: Math.min(maxSx, Math.max(0, -offset.x / scale)),
    sy: Math.min(maxSy, Math.max(0, -offset.y / scale)),
    width: viewWidth,
    height: viewHeight,
  }
}
