/**
 * 多选对齐与分布。
 *
 * user:“对齐分布”+
 * (以选中元素的整体包围盒为基准：左中右、上中下对齐；
 *  分布按首尾之间的剩余空间均分，不改变首尾元素。)
 */

import type { OffsetBox } from './drag.ts'

export type AlignMode = 'left' | 'centerX' | 'right' | 'top' | 'centerY' | 'bottom'

export interface Delta {
  x: number
  y: number
}

function unionOf(boxes: OffsetBox[]) {
  const left = Math.min(...boxes.map((box) => box.left))
  const right = Math.max(...boxes.map((box) => box.left + box.width))
  const top = Math.min(...boxes.map((box) => box.top))
  const bottom = Math.max(...boxes.map((box) => box.top + box.height))
  return { left, right, top, bottom, centerX: (left + right) / 2, centerY: (top + bottom) / 2 }
}

export function alignDeltas(boxes: OffsetBox[], mode: AlignMode): Delta[] {
  if (boxes.length < 2) return boxes.map(() => ({ x: 0, y: 0 }))
  const bounds = unionOf(boxes)
  return boxes.map((box) => {
    switch (mode) {
      case 'left':
        return { x: bounds.left - box.left, y: 0 }
      case 'centerX':
        return { x: bounds.centerX - (box.left + box.width / 2), y: 0 }
      case 'right':
        return { x: bounds.right - (box.left + box.width), y: 0 }
      case 'top':
        return { x: 0, y: bounds.top - box.top }
      case 'centerY':
        return { x: 0, y: bounds.centerY - (box.top + box.height / 2) }
      case 'bottom':
        return { x: 0, y: bounds.bottom - (box.top + box.height) }
      default:
        return { x: 0, y: 0 }
    }
  })
}

/** 首尾不动，中间的按剩余空间均分。少于三个元素不分布。 */
export function distributeDeltas(boxes: OffsetBox[], axis: 'x' | 'y'): Delta[] {
  if (boxes.length < 3) return boxes.map(() => ({ x: 0, y: 0 }))
  const order = boxes
    .map((box, index) => ({ index, start: axis === 'x' ? box.left : box.top, size: axis === 'x' ? box.width : box.height }))
    .sort((left, right) => left.start - right.start)
  const first = order[0]
  const last = order[order.length - 1]
  const span = (last.start + last.size) - first.start
  const occupied = order.reduce((total, item) => total + item.size, 0)
  const gap = (span - occupied) / (order.length - 1)
  const deltas: Delta[] = boxes.map(() => ({ x: 0, y: 0 }))
  let cursor = first.start + first.size + gap
  for (let index = 1; index < order.length - 1; index += 1) {
    const item = order[index]
    const shift = cursor - item.start
    deltas[item.index] = { x: axis === 'x' ? shift : 0, y: axis === 'y' ? shift : 0 }
    cursor += item.size + gap
  }
  return deltas
}
