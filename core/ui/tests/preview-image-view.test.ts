import { describe, expect, it } from 'vitest'
import { annotationSize } from '../src/annotation/draw'
import { ANNOTATION_PALETTE, ANNOTATION_TOOL_COLORS, annotationColor, createAnnotation } from '../src/annotation/model'
import {
  IMAGE_MAX_SCALE,
  centeredView,
  clampScale,
  clampView,
  fitScale,
  imageToScreen,
  scaleAt,
  screenToImage,
  zoomAtCenter,
} from '../src/preview/imageView'

// user:“灯箱应该配套缩放UI，支持Ctrl滚轮…默认大小自适应，左键可拖动”+
// (缩放/拖动全部落在这几个纯函数上：不测 DOM 也能证明“装得下、拖不飞、光标锚点不跑”)。
describe('preview image view math', () => {
  const image = { width: 1600, height: 1000 }
  const viewport = { width: 800, height: 800 }

  it('大图缩到装得下，小图保持 1:1', () => {
    expect(fitScale(image, viewport)).toBeCloseTo(0.5)
    expect(fitScale({ width: 64, height: 64 }, viewport)).toBe(1)
    expect(fitScale({ width: 0, height: 0 }, viewport)).toBe(1)
  })

  it('居中摆放：缩放后的图四周留白相等', () => {
    const view = centeredView(image, viewport, 0.5)
    expect(view).toEqual({ scale: 0.5, x: 0, y: 150 })
  })

  it('装得下时不允许拖动（永远居中）', () => {
    const view = clampView({ scale: 0.5, x: -120, y: 400 }, image, viewport)
    expect(view).toEqual({ scale: 0.5, x: 0, y: 150 })
  })

  it('装不下时夹在边缘，拖不飞', () => {
    const big = { scale: 1, x: 0, y: 0 }
    expect(clampView({ ...big, x: 200, y: 200 }, image, viewport)).toEqual({ scale: 1, x: 0, y: 0 })
    expect(clampView({ ...big, x: -9999, y: -9999 }, image, viewport)).toEqual({ scale: 1, x: -800, y: -200 })
  })

  it('视口坐标与图片坐标可逆', () => {
    const view = { scale: 0.5, x: 40, y: 60 }
    const imagePoint = { x: 320, y: 210 }
    const screen = imageToScreen(view, imagePoint)
    expect(screen).toEqual({ x: 200, y: 165 })
    expect(screenToImage(view, screen)).toEqual(imagePoint)
  })

  it('Ctrl+滚轮以光标为锚：锚点下面的那块图不动', () => {
    const start = centeredView(image, viewport, 0.5)
    // 取中心点：放大到 1:1 后仍有余量，不会被“边缘不留缝”的夹取改写。
    const anchor = { x: 400, y: 400 }
    const before = screenToImage(start, anchor)
    const zoomed = scaleAt(start, image, viewport, 1, anchor)
    const after = screenToImage(zoomed, anchor)
    expect(after.x).toBeCloseTo(before.x)
    expect(after.y).toBeCloseTo(before.y)
    expect(zoomed.scale).toBe(1)
  })

  it('贴到边缘后锚点让位给“不露缝”，这是有意的', () => {
    const start = centeredView(image, viewport, 0.5)
    const zoomed = scaleAt(start, image, viewport, 1, { x: 240, y: 520 })
    // 横向还有余量，锚点照旧；纵向已经顶到下边缘，只让这一维。
    expect(zoomed.x).toBeCloseTo(-240)
    expect(zoomed.y).toBe(-200)
  })

  it('工具条缩放围绕中心，并受上下限约束', () => {
    const start = centeredView(image, viewport, 0.5)
    expect(zoomAtCenter(start, image, viewport, 1.25).scale).toBeCloseTo(0.625)
    expect(clampScale(99)).toBe(IMAGE_MAX_SCALE)
    expect(clampScale(0)).toBeGreaterThan(0)
  })
})

describe('shared annotation model', () => {
  it('标注尺寸跟着图片宽度走，并有上下限', () => {
    expect(annotationSize(400)).toBe(22)
    expect(annotationSize(2000)).toBeCloseTo(60)
    expect(annotationSize(8000)).toBe(64)
  })

  it('颜色：用户选过就用选的，否则用工具默认色', () => {
    expect(annotationColor('arrow', null)).toBe(ANNOTATION_TOOL_COLORS.arrow)
    expect(annotationColor('text', '#123456')).toBe('#123456')
    expect(ANNOTATION_PALETTE).toHaveLength(8)
  })

  it('新标注只有起点，拖拽补点由宿主负责', () => {
    const annotation = createAnnotation(3, 'pen', { x: 10, y: 20 }, '#7ED6A5')
    expect(annotation).toEqual({ id: 3, tool: 'pen', points: [{ x: 10, y: 20 }], color: '#7ED6A5' })
  })
})
