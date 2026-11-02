/**
 * 方块人皮肤：内置默认皮肤生成 + 外部 PNG 解码。
 *
 * 内置皮肤是"画"出来的，不打包任何二进制素材：这样预设角色随代码走，
 * 也不会把第三方皮肤带进发行版。
 */
import { boxFaceUvs, defaultSkinPaint, type BlockyModel, type SkinBox } from './blocky.ts'

export const SKIN_SIZE = 64

/** 按标准网格把默认皮肤画到 64×64 画布上。 */
export function createDefaultSkinCanvas(model: BlockyModel = 'steve'): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = SKIN_SIZE
  canvas.height = SKIN_SIZE
  const context = canvas.getContext('2d')
  if (!context) return canvas
  context.imageSmoothingEnabled = false
  context.clearRect(0, 0, SKIN_SIZE, SKIN_SIZE)
  for (const part of defaultSkinPaint(model)) {
    paintBox(context, part.box, { face: part.face, side: part.side, top: part.top, bottom: part.bottom })
  }
  return canvas
}

function paintBox(
  context: CanvasRenderingContext2D,
  box: SkinBox,
  colors: { face: string; side: string; top: string; bottom: string },
): void {
  const faces = boxFaceUvs(box, SKIN_SIZE, SKIN_SIZE)
  // faces.rects 是 UV（原点左下），这里换算回画布像素。
  const regions: { rect: { u0: number; v0: number; u1: number; v1: number }; color: string }[] = [
    { rect: faces.rects[0], color: colors.side }, // 右
    { rect: faces.rects[1], color: colors.side }, // 左
    { rect: faces.rects[2], color: colors.top }, // 顶
    { rect: faces.rects[3], color: colors.bottom }, // 底
    { rect: faces.rects[4], color: colors.face }, // 前
    { rect: faces.rects[5], color: colors.side }, // 后
  ]
  for (const region of regions) {
    const x = Math.round(region.rect.u0 * SKIN_SIZE)
    const y = Math.round((1 - region.rect.v1) * SKIN_SIZE)
    const width = Math.max(1, Math.round((region.rect.u1 - region.rect.u0) * SKIN_SIZE))
    const height = Math.max(1, Math.round((region.rect.v1 - region.rect.v0) * SKIN_SIZE))
    context.fillStyle = region.color
    context.fillRect(x, y, width, height)
    // 轻微的像素噪点，避免大色块看起来像占位图。
    context.fillStyle = 'rgba(0,0,0,0.06)'
    for (let row = 0; row < height; row += 2) {
      for (let column = (row % 4) / 2; column < width; column += 3) {
        context.fillRect(x + column, y + row, 1, 1)
      }
    }
  }
  // 脸部：眼睛与嘴，位置固定在头前脸的八分之一网格里。
  if (box.w === 8 && box.h === 8) {
    const front = faces.rects[4]
    const left = front.u0 * SKIN_SIZE
    const top = (1 - front.v1) * SKIN_SIZE
    const unit = (front.u1 - front.u0) * SKIN_SIZE / 8
    context.fillStyle = '#1b2430'
    // 两只眼睛（2.5 单位处，各 1×1）
    context.fillRect(Math.round(left + unit * 1.6), Math.round(top + unit * 3.4), Math.round(unit), Math.round(unit))
    context.fillRect(Math.round(left + unit * 5.2), Math.round(top + unit * 3.4), Math.round(unit), Math.round(unit))
    context.fillStyle = '#7a4b3a'
    context.fillRect(Math.round(left + unit * 3), Math.round(top + unit * 5.4), Math.round(unit * 2), Math.round(unit * 0.6))
  }
}

/** 外部 PNG 皮肤 → 画布。尺寸不规范时缩放到 64×64，保持最近邻采样。 */
export async function skinCanvasFromBytes(bytes: Uint8Array): Promise<HTMLCanvasElement> {
  const blob = new Blob([bytes.buffer as ArrayBuffer], { type: 'image/png' })
  const bitmap = await createImageBitmap(blob)
  const canvas = document.createElement('canvas')
  canvas.width = SKIN_SIZE
  canvas.height = SKIN_SIZE
  const context = canvas.getContext('2d')
  if (context) {
    context.imageSmoothingEnabled = false
    context.clearRect(0, 0, SKIN_SIZE, SKIN_SIZE)
    context.drawImage(bitmap, 0, 0, bitmap.width, bitmap.height, 0, 0, SKIN_SIZE, SKIN_SIZE)
  }
  bitmap.close()
  return canvas
}
