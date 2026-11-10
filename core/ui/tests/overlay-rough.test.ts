/**
 * 手绘笔迹验收。
 *
 * user:“箭头和圈选更像手绘风格和手绘出现”+(同一份标记每次重画必须是同一条线，
 * 抖动不能溢出标记范围，也不能产出 SVG 认不出的路径)。
 */
import { describe, expect, it } from 'vitest'
import {
  hashSeed,
  roughArrow,
  roughEllipsePath,
  roughLinePath,
  roughRectPath,
  seededRandom,
} from '@/overlay/rough.ts'

function numbersIn(path: string): number[] {
  return (path.match(/-?\d+(\.\d+)?/g) ?? []).map(Number)
}

describe('手绘路径', () => {
  it('同一个种子画出同一条线', () => {
    const first = roughLinePath([[10, 10], [210, 40]], 42)
    const second = roughLinePath([[10, 10], [210, 40]], 42)
    expect(first).toBe(second)
  })

  it('不同种子画出不同的线', () => {
    expect(roughLinePath([[0, 0], [200, 0]], 1)).not.toBe(roughLinePath([[0, 0], [200, 0]], 2))
  })

  it('随机序列可复现', () => {
    const a = seededRandom(7)
    const b = seededRandom(7)
    expect([a(), a(), a()]).toEqual([b(), b(), b()])
  })

  it('字符串散列稳定且非零', () => {
    expect(hashSeed('mk-abc')).toBe(hashSeed('mk-abc'))
    expect(hashSeed('mk-abc')).not.toBe(hashSeed('mk-abd'))
    expect(hashSeed('')).toBeGreaterThan(0)
  })

  it('只产出 SVG 认识的路径命令', () => {
    const paths = [
      roughLinePath([[0, 0], [120, 60], [240, 10]], 3),
      roughRectPath({ x: 10, y: 20, width: 200, height: 90 }, 4),
      roughEllipsePath({ x: 0, y: 0, width: 160, height: 80 }, 5),
      roughArrow([[0, 0], [180, 40]], 6, 18).shaft,
    ]
    for (const path of paths) {
      expect(path).toMatch(/^M /)
      expect(path.replace(/[MLQZ0-9.,\-\s]/g, '')).toBe('')
    }
  })

  it('矩形抖动不超出自身范围的容差', () => {
    const rect = { x: 100, y: 200, width: 300, height: 120 }
    const values = numbersIn(roughRectPath(rect, 11, 2))
    for (let index = 0; index + 1 < values.length; index += 2) {
      expect(values[index]).toBeGreaterThanOrEqual(rect.x - 6)
      expect(values[index]).toBeLessThanOrEqual(rect.x + rect.width + 6)
      expect(values[index + 1]).toBeGreaterThanOrEqual(rect.y - 6)
      expect(values[index + 1]).toBeLessThanOrEqual(rect.y + rect.height + 6)
    }
  })

  it('椭圆闭合且首尾一致', () => {
    const path = roughEllipsePath({ x: 0, y: 0, width: 120, height: 60 }, 9)
    expect(path.trim().endsWith('Z')).toBe(true)
  })

  it('箭头有杆也有头', () => {
    const arrow = roughArrow([[10, 10], [210, 10]], 12, 20)
    expect(arrow.shaft.length).toBeGreaterThan(0)
    expect(arrow.head.split('M').length - 1).toBe(2)
  })

  it('零长度箭头不出头', () => {
    expect(roughArrow([[10, 10], [10, 10]], 13, 20).head).toBe('')
  })
})
