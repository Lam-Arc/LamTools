import { describe, expect, it } from 'vitest'
import {
  GAP_HIT_MIN_HEIGHT,
  GAP_HIT_MIN_WIDTH,
  buildGapAnnotation,
  chooseGapLevel,
  gapLevelLabel,
  measureGap,
} from '../src/themeStudio/annotation.ts'

/**
 * user:“三级间距标注：大括号 / > / 单段折线；标签在外侧；热区保持屏幕级最小尺寸”+
 * (几何判定独立测试，画布只负责渲染。)
 */

describe('三级间距标注', () => {
  it('按可见间距分三档', () => {
    expect(chooseGapLevel(40)).toBe('brace')
    expect(chooseGapLevel(12)).toBe('brace')
    expect(chooseGapLevel(11.9)).toBe('chevron')
    expect(chooseGapLevel(4)).toBe('chevron')
    expect(chooseGapLevel(3.9)).toBe('segment')
    expect(chooseGapLevel(0)).toBe('segment')
  })

  it('竖向相邻量出上下间距', () => {
    const band = measureGap(
      { left: 0, top: 0, width: 100, height: 40 },
      { left: 0, top: 60, width: 100, height: 40 },
    )
    expect(band).not.toBeNull()
    expect(band!.axis).toBe('vertical')
    expect(band!.gap).toBe(20)
    expect(band!.band.top).toBe(40)
    expect(band!.band.height).toBe(20)
  })

  it('横向相邻量出左右间距', () => {
    const band = measureGap(
      { left: 0, top: 0, width: 40, height: 100 },
      { left: 60, top: 0, width: 40, height: 100 },
    )
    expect(band!.axis).toBe('horizontal')
    expect(band!.gap).toBe(20)
    expect(band!.band.left).toBe(40)
    expect(band!.band.width).toBe(20)
  })

  it('两向都重叠就没有可标注的间距', () => {
    expect(measureGap(
      { left: 0, top: 0, width: 100, height: 100 },
      { left: 20, top: 20, width: 40, height: 40 },
    )).toBeNull()
  })

  it('大间距画括号，标签在间距带外面', () => {
    const annotation = buildGapAnnotation({
      axis: 'vertical',
      gap: 20,
      band: { left: 100, top: 200, width: 160, height: 20 },
    })
    expect(annotation.level).toBe('brace')
    expect(annotation.path.startsWith('M ')).toBe(true)
    expect(annotation.path.match(/L /g)?.length).toBeGreaterThanOrEqual(5)
    expect(annotation.label.y).toBeLessThan(200)
    expect(annotation.label.anchor).toBe('middle')
  })

  it('零间距仍有屏幕级最小热区', () => {
    const annotation = buildGapAnnotation({
      axis: 'vertical',
      gap: 1,
      band: { left: 100, top: 200, width: 160, height: 1 },
    })
    expect(annotation.level).toBe('segment')
    expect(annotation.hit.width).toBeGreaterThanOrEqual(GAP_HIT_MIN_WIDTH)
    expect(annotation.hit.height).toBeGreaterThanOrEqual(GAP_HIT_MIN_HEIGHT)
  })

  it('画布放大时热区按缩放换算，屏幕尺寸不变', () => {
    const annotation = buildGapAnnotation({
      axis: 'horizontal',
      gap: 2,
      scale: 2,
      band: { left: 100, top: 200, width: 2, height: 120 },
    })
    expect(annotation.hit.width).toBeGreaterThanOrEqual(GAP_HIT_MIN_WIDTH / 2)
    expect(annotation.hit.height).toBeGreaterThanOrEqual(GAP_HIT_MIN_HEIGHT / 2)
    expect(annotation.label.anchor).toBe('start')
  })

  it('等级有中文说明', () => {
    expect(gapLevelLabel('brace')).toBe('大括号')
    expect(gapLevelLabel('chevron')).toBe('折角')
    expect(gapLevelLabel('segment')).toBe('线段')
  })
})
