/**
 * user:“1 个就是整图，2 个就是并排，3 个就是并排 3 个，4 个就是四宫格…按照比例去分…
 * 总而言之，它最后出来的东西一定是一个矩形”+(不写死列数：每行按各块的宽高比铺满容器宽度，
 * 行高由「容器宽 ÷ 本行宽高比之和」反算，所以每一行都正好填满，整块必然是一个矩形。)
 *
 * The layout is the classic justified gallery: accumulate items until the row's
 * natural height drops to the target, then that row is stretched to exactly the
 * container width. Mixed aspect ratios therefore tile into rows of different
 * counts — 5 items of 1:1,1:1,2:1,1:1,1:1 become three full-width rows.
 */

export interface MosaicRow {
  /** Inclusive start index into the aspect array. */
  start: number
  /** Exclusive end index. */
  end: number
  /** Height in px this row should render at. */
  height: number
}

const MIN_ASPECT = 0.25
const MAX_ASPECT = 6
const MIN_ROW_HEIGHT = 96

export function partitionMosaicRows(
  aspects: number[],
  width: number,
  targetHeight = 180,
): MosaicRow[] {
  const rows: MosaicRow[] = []
  if (!(width > 0) || aspects.length === 0) return rows

  const safe = aspects.map(aspect => {
    const value = Number.isFinite(aspect) && aspect > 0 ? aspect : 1
    return Math.min(MAX_ASPECT, Math.max(MIN_ASPECT, value))
  })

  let start = 0
  let sum = 0
  for (let index = 0; index < safe.length; index += 1) {
    sum += safe[index]
    const height = width / sum
    const isLast = index === safe.length - 1
    if (height <= targetHeight || isLast) {
      rows.push({ start, end: index + 1, height: Math.max(MIN_ROW_HEIGHT, height) })
      start = index + 1
      sum = 0
    }
  }
  return rows
}

/** Width in px each item of a row should take so the row sums to the container width. */
export function rowItemWidths(aspects: number[], row: MosaicRow, width: number): number[] {
  const slice = aspects.slice(row.start, row.end).map(aspect => {
    const value = Number.isFinite(aspect) && aspect > 0 ? aspect : 1
    return Math.min(MAX_ASPECT, Math.max(MIN_ASPECT, value))
  })
  const total = slice.reduce((sum, aspect) => sum + aspect, 0) || 1
  return slice.map(aspect => (width * aspect) / total)
}
