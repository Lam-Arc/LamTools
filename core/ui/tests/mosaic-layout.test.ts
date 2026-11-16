import { describe, expect, it } from 'vitest'

import { partitionMosaicRows, rowItemWidths } from '@/helpers/mosaicLayout.ts'

/**
 * user:“1 个就是整图，2 个就是并排，3 个就是并排 3 个，4 个就是四宫格…按照比例去分…
 * 总而言之，它最后出来的东西一定是一个矩形”+(分行的唯一硬约束：每一行的宽度都等于容器宽，
 * 于是整块必然是矩形；一行放几个由宽高比决定，不写死列数。)
 */

const GAP = 6

function rowWidths(aspects: number[], width: number, target = 180) {
  return partitionMosaicRows(aspects, width, target).map(row => {
    const usable = width - GAP * (row.end - row.start - 1)
    const widths = rowItemWidths(aspects, row, usable)
    return { row, usable, widths, total: widths.reduce((sum, value) => sum + value, 0) }
  })
}

describe('mosaic layout', () => {
  it('keeps a single item on its own full-width row', () => {
    const rows = partitionMosaicRows([1], 600)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ start: 0, end: 1 })
    expect(rows[0].height).toBeCloseTo(600, 5)
  })

  it('pairs two square items into one row', () => {
    const rows = partitionMosaicRows([1, 1], 600)
    expect(rows).toHaveLength(1)
    expect(rows[0].end).toBe(2)
    expect(rows[0].height).toBeCloseTo(300, 5)
  })

  it('fills every row to the container width for mixed ratios', () => {
    // 1:1, 1:1, 2:1, 1:1, 1:1 —— 用户举的五张图
    const aspects = [1, 1, 2, 1, 1]
    const rows = rowWidths(aspects, 600)
    expect(rows.length).toBeGreaterThan(0)
    for (const { usable, total } of rows) {
      expect(total).toBeCloseTo(usable, 4)
    }
    // 所有条目都被覆盖且不重复
    const covered = rows.flatMap(({ row }) => Array.from({ length: row.end - row.start }, (_, index) => row.start + index))
    expect(covered).toEqual([0, 1, 2, 3, 4])
  })

  it('keeps rows full-width when one item is twice as wide', () => {
    const aspects = [1, 1, 1, 1, 1, 2]
    const rows = rowWidths(aspects, 720)
    for (const { usable, total } of rows) {
      expect(total).toBeCloseTo(usable, 4)
    }
    expect(rows.flatMap(({ row }) => Array.from({ length: row.end - row.start }, (_, index) => row.start + index)))
      .toEqual([0, 1, 2, 3, 4, 5])
  })

  it('degrades to one item per row on a narrow container', () => {
    const rows = partitionMosaicRows([1, 1, 1, 1], 160, 180)
    expect(rows).toHaveLength(4)
    for (const row of rows) expect(row.end - row.start).toBe(1)
  })

  it('never returns rows for an empty or zero-width input', () => {
    expect(partitionMosaicRows([], 600)).toHaveLength(0)
    expect(partitionMosaicRows([1, 1], 0)).toHaveLength(0)
  })
})
