import { describe, expect, it } from 'vitest'

import { parseChartSpec } from '@/helpers/chartSpec.ts'

/**
 * user:“图表落地，柱状，折线，饼图都支持”+(载荷先校验再画：坏数据要给出一句能照着改的
 * 错误，而不是一块空画布。)
 */

const bar = {
  type: 'bar',
  title: '近六周会话量',
  unit: '次',
  categories: ['-3w', '-2w', '-1w'],
  series: [{ name: '会话量', data: [12, 18, 25] }],
}

describe('parseChartSpec', () => {
  it('accepts a bar spec and keeps order and units', () => {
    const result = parseChartSpec(JSON.stringify(bar))
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.spec.type).toBe('bar')
    expect(result.spec.title).toBe('近六周会话量')
    expect(result.spec.unit).toBe('次')
    expect(result.spec.categories).toEqual(['-3w', '-2w', '-1w'])
    expect(result.spec.series[0]).toEqual({ name: '会话量', data: [12, 18, 25] })
  })

  it('accepts a line spec with several series', () => {
    const result = parseChartSpec(JSON.stringify({
      type: 'line',
      categories: ['1月', '2月'],
      series: [{ name: 'A', data: [1, 2] }, { name: 'B', data: [3, 4] }],
    }))
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.spec.series).toHaveLength(2)
  })

  it('accepts a pie spec and falls back to positional labels', () => {
    const result = parseChartSpec(JSON.stringify({
      type: 'pie',
      series: [{ name: '占比', data: [3, 7] }],
    }))
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.spec.categories).toEqual(['第 1 项', '第 2 项'])
    expect(result.spec.series).toHaveLength(1)
  })

  it('names unnamed series instead of rendering a blank legend', () => {
    const result = parseChartSpec(JSON.stringify({
      type: 'bar',
      categories: ['A'],
      series: [[5]],
    }))
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.spec.series[0].name).toBe('系列 1')
  })

  it('rejects malformed payloads with an actionable message', () => {
    expect(parseChartSpec('').ok).toBe(false)
    expect(parseChartSpec('not json').ok).toBe(false)
    const wrongType = parseChartSpec(JSON.stringify({ type: 'scatter', categories: ['A'], series: [{ data: [1] }] }))
    expect(wrongType.ok).toBe(false)
    if (!wrongType.ok) expect(wrongType.error).toContain('type')

    const noCategories = parseChartSpec(JSON.stringify({ type: 'bar', series: [{ data: [1] }] }))
    expect(noCategories.ok).toBe(false)
    if (!noCategories.ok) expect(noCategories.error).toContain('categories')

    const mismatch = parseChartSpec(JSON.stringify({
      type: 'line', categories: ['A', 'B'], series: [{ data: [1] }],
    }))
    expect(mismatch.ok).toBe(false)
    if (!mismatch.ok) expect(mismatch.error).toContain('数量不一致')

    const notNumbers = parseChartSpec(JSON.stringify({
      type: 'bar', categories: ['A'], series: [{ data: ['x'] }],
    }))
    expect(notNumbers.ok).toBe(false)

    const singleSlice = parseChartSpec(JSON.stringify({ type: 'pie', series: [{ data: [1] }] }))
    expect(singleSlice.ok).toBe(false)
    if (!singleSlice.ok) expect(singleSlice.error).toContain('扇区')
  })

  it('caps runaway payloads instead of hanging the renderer', () => {
    const manySeries = parseChartSpec(JSON.stringify({
      type: 'line',
      categories: ['A'],
      series: Array.from({ length: 13 }, () => ({ data: [1] })),
    }))
    expect(manySeries.ok).toBe(false)

    const manyPoints = parseChartSpec(JSON.stringify({
      type: 'line',
      categories: Array.from({ length: 600 }, (_, index) => `p${index}`),
      series: [{ data: Array.from({ length: 600 }, () => 1) }],
    }))
    expect(manyPoints.ok).toBe(false)
    if (!manyPoints.ok) expect(manyPoints.error).toContain('数据点')
  })

  it('accepts a radar spec whose categories are the axes', () => {
    const result = parseChartSpec(JSON.stringify({
      type: 'radar',
      title: '能力对比',
      categories: ['速度', '稳定', '成本', '扩展', '易用'],
      series: [
        { name: '方案 A', data: [80, 60, 70, 50, 90] },
        { name: '方案 B', data: [60, 80, 50, 70, 75] },
      ],
    }))
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.spec.type).toBe('radar')
    expect(result.spec.categories).toHaveLength(5)
    expect(result.spec.series).toHaveLength(2)
    // 雷达不参与面积/曲线修饰
    expect(result.spec.area).toBe(false)
    expect(result.spec.smooth).toBe(false)
  })

  it('rejects a radar with too few axes or mismatched data', () => {
    const twoAxes = parseChartSpec(JSON.stringify({
      type: 'radar', categories: ['A', 'B'], series: [{ data: [1, 2] }],
    }))
    expect(twoAxes.ok).toBe(false)
    if (!twoAxes.ok) expect(twoAxes.error).toContain('3 个维度')

    const mismatch = parseChartSpec(JSON.stringify({
      type: 'radar', categories: ['A', 'B', 'C'], series: [{ data: [1, 2] }],
    }))
    expect(mismatch.ok).toBe(false)
    if (!mismatch.ok) expect(mismatch.error).toContain('维度数量不一致')
  })

  it('carries smooth and area as line modifiers', () => {
    const result = parseChartSpec(JSON.stringify({
      type: 'line', smooth: true, area: true,
      categories: ['A', 'B'], series: [{ name: 'n', data: [1, 2] }],
    }))
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.spec.smooth).toBe(true)
    expect(result.spec.area).toBe(true)
  })

  it('lets one series override the chart type for bar+line mixes', () => {
    const result = parseChartSpec(JSON.stringify({
      type: 'bar',
      categories: ['A', 'B'],
      series: [
        { name: '柱', data: [1, 2], type: 'bar' },
        { name: '线', data: [3, 4], type: 'line' },
      ],
    }))
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.spec.series[0].type).toBe('bar')
    expect(result.spec.series[1].type).toBe('line')

    const bad = parseChartSpec(JSON.stringify({
      type: 'bar', categories: ['A'], series: [{ data: [1], type: 'scatter' }],
    }))
    expect(bad.ok).toBe(false)
    if (!bad.ok) expect(bad.error).toContain('series[0].type')
  })
})
