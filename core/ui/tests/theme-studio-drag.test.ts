import { describe, expect, it } from 'vitest'
import { snapOffset, SNAP_THRESHOLD } from '../src/themeStudio/drag.ts'

/**
 * user:“磁吸、对齐、间距调整”+
 * (粘贴到父容器边缘、中心对齐要吸附；超过阈值不吸；偏移要有上限。)
 */
const box = { left: 100, top: 100, width: 200, height: 80 }

describe('拖拽吸附', () => {
  it('右边缘贴到参考线', () => {
    const result = snapOffset(box, { x: 0, y: 0 }, { x: [302], y: [] })
    expect(result.x).toBe(2)
    expect(result.guideX).toBe(302)
  })

  it('中心线对齐', () => {
    const result = snapOffset(box, { x: 0, y: 0 }, { x: [200], y: [] })
    expect(result.x).toBe(0)
    expect(result.guideX).toBe(200)
  })

  it('超过阈值不吸附', () => {
    const result = snapOffset(box, { x: 0, y: 0 }, { x: [300 + SNAP_THRESHOLD + 1], y: [] })
    expect(result.x).toBe(0)
    expect(result.guideX).toBeNull()
  })

  it('纵向同样按上中下三条边吸附', () => {
    const result = snapOffset(box, { x: 0, y: 10 }, { x: [], y: [190] })
    expect(result.y).toBe(10)
    expect(result.guideY).toBe(190)
  })

  it('偏移有上限', () => {
    const result = snapOffset(box, { x: 99999, y: -99999 }, { x: [], y: [] })
    expect(result.x).toBe(4000)
    expect(result.y).toBe(-4000)
  })
})
