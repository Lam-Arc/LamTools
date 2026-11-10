/**
 * Desktop Overlay 覆盖层几何验收。
 *
 * user:“标记可跟随窗口和对象，用户能直接点击、圈选、批注，与 Agent 实时互动。”
 * +(跟随不是重画：标记按创建时窗口的原矩形存绝对屏幕坐标，窗口移动/缩放后
 * 在渲染前换算；窗口消失就退回原坐标，不能凭空消失。)
 */
import { describe, expect, it } from 'vitest'
import {
  arrowGeometry,
  ellipseFromPoints,
  hitTestMarks,
  isExpired,
  penPath,
  rectFromPoints,
  resolveMark,
  resolveMarkPoints,
  visibleMarks,
  type OverlayMark,
  type ScreenWindow,
} from '../src/overlay/model.ts'

function mark(overrides: Partial<OverlayMark> = {}): OverlayMark {
  return {
    id: 'mk-1',
    kind: 'arrow',
    points: [
      [200, 200],
      [300, 300],
    ],
    color: '#ff5c8a',
    width: 3,
    text: '',
    ttl: 30,
    window: null,
    window_missing: false,
    label: '',
    created_at: 1000,
    expires_at: 1030,
    source: 'agent',
    ...overrides,
  }
}

function windowAt(id: string, x: number, y: number, width: number, height: number): ScreenWindow {
  return { id, title: `window-${id}`, bounds: { x, y, width, height }, z: 1 }
}

describe('窗口跟随', () => {
  it('窗口平移时标记整体跟着平移', () => {
    const target = mark({
      window: { id: 42, title: '记事本', bounds: [100, 100, 800, 600] },
    })
    const points = resolveMarkPoints(target, [windowAt('42', 150, 120, 800, 600)])
    expect(points).toEqual([
      [250, 220],
      [350, 320],
    ])
  })

  it('窗口缩放时按比例换算', () => {
    const target = mark({
      window: { id: 42, title: '记事本', bounds: [100, 100, 800, 600] },
    })
    const points = resolveMarkPoints(target, [windowAt('42', 100, 100, 1600, 1200)])
    expect(points).toEqual([
      [300, 300],
      [500, 500],
    ])
  })

  it('窗口消失时退回创建时的屏幕坐标', () => {
    const target = mark({
      window: { id: 42, title: '记事本', bounds: [100, 100, 800, 600] },
    })
    expect(resolveMarkPoints(target, [])).toEqual(target.points)
  })

  it('窗口 id 用字符串比较也能对上', () => {
    const target = mark({ window: { id: 42, title: '记事本', bounds: [0, 0, 100, 100] } })
    expect(resolveMarkPoints(target, [windowAt('42', 10, 10, 100, 100)])).toEqual([
      [210, 210],
      [310, 310],
    ])
  })

  it('resolveMark 只替换点，不动其它字段', () => {
    const target = mark({ window: { id: 42, title: '记事本', bounds: [0, 0, 100, 100] } })
    const resolved = resolveMark(target, [windowAt('42', 10, 10, 100, 100)])
    expect(resolved.id).toBe('mk-1')
    expect(resolved.kind).toBe('arrow')
    expect(resolved.points[0]).toEqual([210, 210])
    expect(target.points[0]).toEqual([200, 200])
  })
})

describe('过期', () => {
  it('超过 expires_at 就不再显示', () => {
    expect(isExpired(mark({ expires_at: 1000 }), 1001)).toBe(true)
    expect(isExpired(mark({ expires_at: 1000 }), 1000)).toBe(true)
    expect(isExpired(mark({ expires_at: 1000 }), 999)).toBe(false)
  })

  it('visibleMarks 过滤掉过期的，保留未过期的', () => {
    const live = mark({ id: 'live', expires_at: 2000 })
    const dead = mark({ id: 'dead', expires_at: 1000 })
    expect(visibleMarks([live, dead], 1500).map(item => item.id)).toEqual(['live'])
  })
})

describe('形状几何', () => {
  it('箭头从起点指向终点，三角头部落在终点', () => {
    const geometry = arrowGeometry([
      [0, 0],
      [100, 0],
    ], 3)
    expect(geometry.angle).toBeCloseTo(0)
    expect(geometry.length).toBeCloseTo(100)
    expect(geometry.head).toContain('100')
  })

  it('箭头长度为零时不给头部路径', () => {
    const geometry = arrowGeometry([
      [10, 10],
      [10, 10],
    ], 3)
    expect(geometry.head).toBe('')
  })

  it('矩形从任意两个对角点归一化', () => {
    expect(rectFromPoints([[300, 400], [100, 200]])).toEqual({ x: 100, y: 200, width: 200, height: 200 })
  })

  it('椭圆用外接矩形描述', () => {
    expect(ellipseFromPoints([[0, 0], [100, 50]])).toEqual({
      cx: 50,
      cy: 25,
      rx: 50,
      ry: 25,
    })
  })

  it('自由涂鸦生成连续路径', () => {
    expect(
      penPath([
        [0, 0],
        [10, 10],
        [20, 5],
      ]),
    ).toBe('M 0 0 L 10 10 L 20 5')
  })
})

describe('命中测试', () => {
  it('点在文字标记附近命中', () => {
    const text = mark({ id: 'text-1', kind: 'text', text: '看这里', points: [[500, 500]] })
    expect(hitTestMarks([text], [506, 505], 12)?.id).toBe('text-1')
  })

  it('点在远处不命中', () => {
    const text = mark({ id: 'text-1', kind: 'text', text: '看这里', points: [[500, 500]] })
    expect(hitTestMarks([text], [700, 700], 12)).toBeNull()
  })

  it('矩形标记内部命中', () => {
    const box = mark({ id: 'box', kind: 'rect', points: [[100, 100], [300, 300]] })
    expect(hitTestMarks([box], [200, 200], 6)?.id).toBe('box')
  })

  it('多个标记重叠时返回最上面的一个', () => {
    const lower = mark({ id: 'lower', kind: 'text', text: 'A', points: [[500, 500]] })
    const upper = mark({ id: 'upper', kind: 'text', text: 'B', points: [[502, 502]] })
    expect(hitTestMarks([lower, upper], [501, 501], 12)?.id).toBe('upper')
  })
})

import {
  lifeOpacity,
  motionProgress,
  shapeProgress,
  stickerPopScale,
  strokeStyle,
} from '../src/overlay/motion.ts'

function timedMark(overrides: Partial<OverlayMark> = {}): OverlayMark {
  return mark({
    created_at: 100,
    ttl: 3,
    motion: { type: 'fade', duration: 3, fade: 0.5, easing: 'ease-out', from: 'center' },
    ...overrides,
  })
}

describe('瞬时表演的时间计算', () => {
  it('进入阶段淡入，停留阶段全亮，最后按 fade 淡出', () => {
    const item = timedMark()
    expect(lifeOpacity(item, 100.09)).toBeCloseTo(0.5, 2)
    expect(lifeOpacity(item, 101.5)).toBe(1)
    expect(lifeOpacity(item, 102.75)).toBeCloseTo(0.5, 2)
    expect(lifeOpacity(item, 103.1)).toBe(0)
  })

  it('ttl 到点就是 0，不管 fade 多大', () => {
    const item = timedMark({ ttl: 0.5, motion: { type: 'fade', duration: 0.5, fade: 0.5, easing: 'linear', from: 'center' } })
    expect(lifeOpacity(item, 100.5)).toBe(0)
  })

  it('弹幕按 motion.duration 推进，默认占满寿命', () => {
    const item = timedMark({ motion: { type: 'danmaku', duration: 3, fade: 0.5, easing: 'linear', from: 'right' } })
    expect(motionProgress(item, 101.5)).toBeCloseTo(0.5, 2)
    expect(motionProgress(item, 104)).toBe(1)
  })

  it('表情包开口从 0 弹到 1，中途有过冲', () => {
    const sticker = timedMark({ motion: { type: 'pop', duration: 0.6, fade: 0.3, easing: 'ease-out', from: 'center' } })
    expect(stickerPopScale(sticker, 100)).toBeCloseTo(0, 3)
    expect(stickerPopScale(sticker, 100.4)).toBeGreaterThan(1)
    expect(stickerPopScale(sticker, 101)).toBe(1)
  })

  it('SVG 图形按到达时间逐个画，后到的从 0 开始', () => {
    const first = { type: 'path', added_at: 1000 }
    const second = { type: 'path', added_at: 1000.4 }
    const draw = { mode: 'stroke' as const, duration: 0.4 }
    expect(shapeProgress(first, draw, 1000.2)).toBeCloseTo(0.5, 2)
    expect(shapeProgress(second, draw, 1000.2)).toBe(0)
    expect(shapeProgress(second, draw, 1000.9)).toBe(1)
  })

  it('描边用归一化 dashoffset，填充跟着进度长出来', () => {
    const shape = { type: 'circle', added_at: 1000 }
    const style = strokeStyle(shape, { mode: 'stroke', duration: 0.4 }, 1000.1, 0.8)
    expect(style.pathLength).toBe(1)
    expect(style.strokeDasharray).toBe('1')
    expect(style.strokeDashoffset).toBeCloseTo(0.75, 2)
    expect(style.fillOpacity).toBeCloseTo(0.2, 2)
  })

  it('draw 关闭时直接完整显示', () => {
    const shape = { type: 'circle', added_at: 1000 }
    expect(shapeProgress(shape, { mode: 'none', duration: 0 }, 1000)).toBe(1)
    expect(strokeStyle(shape, { mode: 'none', duration: 0 }, 1000).fillOpacity).toBe(1)
  })
})
