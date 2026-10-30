import { describe, expect, it } from 'vitest'
import { alignDeltas, distributeDeltas } from '../src/themeStudio/align.ts'

/**
 * user:“对齐分布”+
 * (左中右与上中下按整体包围盒对齐；分布只挪中间元素，首尾不动。)
 */
const boxes = [
  { left: 100, top: 100, width: 40, height: 20 },
  { left: 200, top: 140, width: 60, height: 30 },
  { left: 320, top: 120, width: 20, height: 40 },
]

describe('多选对齐', () => {
  it('左对齐到整体左边界', () => {
    const deltas = alignDeltas(boxes, 'left')
    expect(deltas.map((delta) => delta.x)).toEqual([0, -100, -220])
    expect(deltas.every((delta) => delta.y === 0)).toBe(true)
  })

  it('水平居中到整体中心', () => {
    const deltas = alignDeltas(boxes, 'centerX')
    const center = (100 + 340) / 2
    expect(deltas[1].x).toBeCloseTo(center - 230)
    expect(deltas[2].x).toBeCloseTo(center - 330)
  })

  it('底对齐到整体底边', () => {
    const deltas = alignDeltas(boxes, 'bottom')
    expect(deltas.map((delta) => delta.y)).toEqual([50, 0, 10])
  })

  it('少于两个元素不动', () => {
    expect(alignDeltas([boxes[0]], 'left')).toEqual([{ x: 0, y: 0 }])
  })
})

describe('分布', () => {
  it('水平分布让中间元素等距', () => {
    const deltas = distributeDeltas(boxes, 'x')
    expect(deltas[0]).toEqual({ x: 0, y: 0 })
    expect(deltas[2]).toEqual({ x: 0, y: 0 })
    const span = 340 - 100
    const occupied = 40 + 60 + 20
    const gap = (span - occupied) / 2
    expect(deltas[1].x).toBeCloseTo(100 + 40 + gap - 200)
  })

  it('纵向分布同样只动中间', () => {
    const deltas = distributeDeltas(boxes, 'y')
    // 按上边界排序：index 0 是首个，index 1 是最后一个，index 2 才是中间的那个。
    expect(deltas[0]).toEqual({ x: 0, y: 0 })
    expect(deltas[1]).toEqual({ x: 0, y: 0 })
    expect(deltas[2].y).toBeCloseTo(-10)
  })

  it('少于三个元素不分布', () => {
    expect(distributeDeltas(boxes.slice(0, 2), 'x')).toEqual([{ x: 0, y: 0 }, { x: 0, y: 0 }])
  })
})
