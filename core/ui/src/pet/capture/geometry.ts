/**
 * 截图框选的纯几何计算。
 *
 * user:“重新设计与实现 Ping 的框选工具”+(把"截图像素 → 窗口坐标 → 导出裁剪"
 * 从组件里抽出来单独测试：DPI 缩放、多显示器原点、反向拖拽都不能靠肉眼验。)
 */
import type { CapturedFrame } from '../bridge.ts'

export interface CaptureRect {
  x: number
  y: number
  width: number
  height: number
}

export interface CaptureRegion {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface CaptureDisplayRect {
  /** 截图像素 → CSS 像素。 */
  scale: number
  offsetX: number
  offsetY: number
  width: number
  height: number
}

/** 把整张截图等比放进窗口，居中显示（多屏/DPI 下窗口与截图比例可能不同）。 */
export function displayRectFor(
  frameWidth: number,
  frameHeight: number,
  viewWidth: number,
  viewHeight: number,
): CaptureDisplayRect {
  const safeFrameWidth = Math.max(1, frameWidth)
  const safeFrameHeight = Math.max(1, frameHeight)
  const scale = Math.min(viewWidth / safeFrameWidth, viewHeight / safeFrameHeight)
  const width = safeFrameWidth * scale
  const height = safeFrameHeight * scale
  return {
    scale,
    offsetX: (viewWidth - width) / 2,
    offsetY: (viewHeight - height) / 2,
    width,
    height,
  }
}

/** 反向拖拽也得到正的矩形；太小的框选视为"没有框选"。 */
export function normalizeRegion(region: CaptureRegion | null, min = 8): CaptureRect | null {
  if (!region) return null
  const x = Math.min(region.x1, region.x2)
  const y = Math.min(region.y1, region.y2)
  const width = Math.abs(region.x2 - region.x1)
  const height = Math.abs(region.y2 - region.y1)
  if (width < min || height < min) return null
  return { x, y, width, height }
}

/** 窗口 CSS 坐标 → 截图像素坐标（含黑边偏移，并夹在截图范围内）。 */
export function pointToFrame(
  clientX: number,
  clientY: number,
  frameWidth: number,
  frameHeight: number,
  display: CaptureDisplayRect,
): { x: number; y: number } {
  const scale = display.scale > 0 ? display.scale : 1
  return {
    x: Math.min(frameWidth, Math.max(0, (clientX - display.offsetX) / scale)),
    y: Math.min(frameHeight, Math.max(0, (clientY - display.offsetY) / scale)),
  }
}

/** 截图像素坐标 → 窗口 CSS 坐标（文字块输入框定位用）。 */
export function frameToClient(
  x: number,
  y: number,
  display: CaptureDisplayRect,
): { left: number; top: number } {
  return {
    left: display.offsetX + x * display.scale,
    top: display.offsetY + y * display.scale,
  }
}

/** 实际导出区域：没框选（或框太小）时发送整屏，与旧行为一致。 */
export function cropFor(region: CaptureRect | null, frameWidth: number, frameHeight: number): CaptureRect {
  if (region) return region
  return { x: 0, y: 0, width: frameWidth, height: frameHeight }
}

/** 导出图片在屏幕上的位置（物理像素 + 显示器缩放）。 */
export function selectionMeta(
  frame: Pick<CapturedFrame, 'x' | 'y' | 'scale'>,
  crop: CaptureRect,
): { x: number; y: number; width: number; height: number; scale: number } {
  return {
    x: frame.x + crop.x,
    y: frame.y + crop.y,
    width: crop.width,
    height: crop.height,
    scale: frame.scale,
  }
}

/**
 * 标注层带过来的屏幕选区 → 截图内像素。
 *
 * user:“合并，这样更干净”+(Ping 自己框选时是窗口坐标；标注层已经给出屏幕
 * 物理像素，必须按截图原点换算一次，DPI 和副屏负坐标都靠这一步对齐。)
 */
export function regionToFrame(
  region: readonly [number, number, number, number],
  frame: Pick<CapturedFrame, 'x' | 'y' | 'width' | 'height'>,
  min = 8,
): CaptureRegion | null {
  const x1 = Math.max(0, region[0] - frame.x)
  const y1 = Math.max(0, region[1] - frame.y)
  const x2 = Math.min(frame.width, region[0] + region[2] - frame.x)
  const y2 = Math.min(frame.height, region[1] + region[3] - frame.y)
  if (x2 - x1 < min || y2 - y1 < min) return null
  return { x1, y1, x2, y2 }
}
