/**
 * 弹幕布局验收。
 *
 * user:“弹幕位置调整一下，30%上方屏幕，速度根据长度调整快慢，越长越慢，
 * 设置中支持调节倍速、字体、字号”+(轨道限定在上方 30%，长句更慢，倍速整体缩放)。
 */
import { describe, expect, it } from 'vitest'
import {
  DANMAKU_BAND_RATIO,
  danmakuLayout,
  danmakuSpeed,
  estimateTextWidth,
  DEFAULT_DANMAKU_SETTINGS,
} from '@/overlay/motion.ts'
import type { OverlayMark } from '@/overlay/model.ts'

const SCREEN_HEIGHT = 1440
/** 2560×1440 屏幕在 125% 缩放下的页面视口，页面按这个排轨道。 */
function viewport() {
  return { cssHeight: 1152, physicalHeight: SCREEN_HEIGHT }
}

// ttl 默认给足：轨道与速度的排序要看跨屏时间，不能被寿命夹住。
function mark(text: string, y = 200, from: 'right' | 'left' = 'right', ttl = 60): OverlayMark {
  return {
    id: `mk-${text.length}`,
    kind: 'danmaku',
    points: [[0, y]],
    color: '#ffffff',
    width: 3,
    text,
    ttl,
    motion: {
      type: 'danmaku',
      duration: ttl,
      fade: 0.4,
      easing: 'linear',
      from,
    },
    window: null,
    window_missing: false,
    label: '',
    created_at: 0,
    expires_at: 6,
    source: 'agent',
  }
}

describe('弹幕轨道', () => {
  it('所有弹幕都落在上方 30% 的带子里', () => {
    const band = SCREEN_HEIGHT * DANMAKU_BAND_RATIO
    for (const y of [0, 200, 700, 1439]) {
      const layout = danmakuLayout(mark('测试弹幕', y), viewport(), 2560, DEFAULT_DANMAKU_SETTINGS)
      expect(layout.top).toBeGreaterThanOrEqual(8)
      expect(layout.top).toBeLessThan(band)
    }
  })

  it('锚点挨得近的弹幕也分行，不会叠在一起', () => {
    // 真机 2560×1440、页面视口 1384×779，三条锚点 90/180/270 曾经只差 12px，
    // 20px 字号的字高 32px，三条直接压成一坨。
    const geometry = { cssHeight: 779, physicalHeight: 1440 }
    const settings = { ...DEFAULT_DANMAKU_SETTINGS, fontSize: 20 }
    const tops = [90, 180, 270].map(y => danmakuLayout(mark('同一批弹幕', y), geometry, 1384, settings).top)
    const lineHeight = settings.fontSize * 1.6
    for (const [index, top] of tops.entries()) {
      if (index === 0) continue
      expect(top - tops[index - 1]).toBeGreaterThanOrEqual(lineHeight)
    }
  })

  it('越靠下的锚点排得越靠下', () => {
    const high = danmakuLayout(mark('同一条弹幕', 88), viewport(), 2560, DEFAULT_DANMAKU_SETTINGS)
    const low = danmakuLayout(mark('同一条弹幕', 1000), viewport(), 2560, DEFAULT_DANMAKU_SETTINGS)
    expect(low.top).toBeGreaterThan(high.top)
  })
})

describe('弹幕速度', () => {
  it('越长越慢', () => {
    const short = danmakuSpeed('短句', 24, 1)
    const long = danmakuSpeed('这是一条很长很长的弹幕内容，用来验证长句会放慢速度', 24, 1)
    expect(long).toBeLessThan(short)
  })

  it('倍速越大速度越快', () => {
    const normal = danmakuSpeed('测试', 24, 1)
    const fast = danmakuSpeed('测试', 24, 2)
    expect(fast).toBeGreaterThan(normal)
    expect(fast / normal).toBeCloseTo(2, 1)
  })

  it('字号越大宽度越大', () => {
    expect(estimateTextWidth('测试文本', 30)).toBeGreaterThan(estimateTextWidth('测试文本', 20))
  })

  it('长句的停留时间明显更久', () => {
    const short = danmakuLayout(mark('短'), viewport(), 2560, DEFAULT_DANMAKU_SETTINGS)
    const long = danmakuLayout(mark('这是一条很长的弹幕内容用来验证时长会拉长'), viewport(), 2560, DEFAULT_DANMAKU_SETTINGS)
    expect(long.duration).toBeGreaterThan(short.duration)
  })

  it('倍速加倍时屏幕上的总时长缩短', () => {
    const normal = danmakuLayout(mark('一条普通长度的弹幕'), viewport(), 2560, DEFAULT_DANMAKU_SETTINGS)
    const fast = danmakuLayout(mark('一条普通长度的弹幕'), viewport(), 2560, {
      ...DEFAULT_DANMAKU_SETTINGS,
      speed: 2,
    })
    expect(fast.duration).toBeLessThan(normal.duration)
  })

  it('寿命比跨屏时间短时按寿命收短，不会飘到一半被抹掉', () => {
    const shortLived = mark('一条普通长度的弹幕', 200, 'right', 2)
    const layout = danmakuLayout(shortLived, viewport(), 2560, DEFAULT_DANMAKU_SETTINGS)
    expect(layout.duration).toBeLessThanOrEqual(2)
    expect(layout.duration).toBeGreaterThan(0)
  })

  it('图片弹幕按图片宽度算速度，图越宽飘得越慢', () => {
    const settings = DEFAULT_DANMAKU_SETTINGS
    const narrow = danmakuLayout(
      { ...mark(''), image: { asset: 'a.png', width: 60 } },
      viewport(),
      2560,
      settings,
    )
    const wide = danmakuLayout(
      { ...mark(''), image: { asset: 'a.png', width: 600 } },
      viewport(),
      2560,
      settings,
    )
    expect(wide.duration).toBeGreaterThan(narrow.duration)
  })

  it('从左边进入的弹幕保留方向标记', () => {
    expect(danmakuLayout(mark('来啦', 100, 'left'), viewport(), 2560, DEFAULT_DANMAKU_SETTINGS).fromLeft).toBe(true)
  })
})
