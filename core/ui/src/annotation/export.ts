/**
 * 标注导出：把标注烧进图片，产出一张新的 PNG。
 *
 * user:“『引用』…直接将已标注/未标注则为原图直接加入输入框”+
 * (有标注时按图片原始像素合成一张 PNG：屏幕上看的是什么样，导出的就是什么样；
 *  裁剪只在需要时传，标注坐标始终是整图坐标，不会被裁掉一截。)
 */
import { drawAnnotations } from './draw'
import type { Annotation } from './model'

export interface AnnotationCrop {
  x: number
  y: number
  width: number
  height: number
}

export interface AnnotatedPngRequest {
  /** 已经解码好的图片（`HTMLImageElement` / `ImageBitmap` 都行）。 */
  image: CanvasImageSource
  /** 整图宽高（图片像素）。 */
  width: number
  height: number
  annotations: readonly Annotation[]
  /** 需要裁切时才传；不传就是整张图。 */
  crop?: AnnotationCrop | null
}

/** 合成 PNG。标注尺寸按整图宽度推导，和屏幕上同一套规则。 */
export async function renderAnnotatedPng(request: AnnotatedPngRequest): Promise<Blob> {
  const crop = request.crop
  const width = Math.max(1, Math.round(crop?.width || request.width))
  const height = Math.max(1, Math.round(crop?.height || request.height))
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('无法创建标注画布')
  context.drawImage(
    request.image,
    crop?.x || 0, crop?.y || 0, width, height,
    0, 0, width, height,
  )
  context.save()
  context.translate(-(crop?.x || 0), -(crop?.y || 0))
  drawAnnotations(context, request.annotations, request.width)
  context.restore()
  const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/png'))
  if (!blob) throw new Error('标注图编码失败')
  return blob
}
