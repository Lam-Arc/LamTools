import type { KnowledgeItem, Relation } from './types'

export interface StudyLayoutPosition { x: number; y: number }

function valid(position: StudyLayoutPosition | undefined): position is StudyLayoutPosition {
  return Boolean(position && Number.isFinite(position.x) && Number.isFinite(position.y))
}

/**
 * Deterministic local 2-D layered layout.  It intentionally does not run a
 * force simulation: a force graph makes saved Study pages drift, scales as
 * O(n²), and gives the user no stable relation direction.  Existing positions
 * remain authoritative; only newly loaded nodes are assigned a layer/row.
 */
export function stableLayeredStudyLayout(
  items: KnowledgeItem[],
  relations: Relation[],
  preserved: Record<string, StudyLayoutPosition> = {},
): Record<string, StudyLayoutPosition> {
  const ordered = items
    .filter(item => item.id)
    .slice()
    .sort((left, right) => left.id.localeCompare(right.id))
  const ids = new Set(ordered.map(item => item.id))
  const incoming = new Map<string, string[]>()
  const outgoing = new Map<string, string[]>()
  ordered.forEach(item => { incoming.set(item.id, []); outgoing.set(item.id, []) })
  relations.forEach(relation => {
    if (!ids.has(relation.source) || !ids.has(relation.target)) return
    // related is deliberately not a layout constraint.  It does not encode a
    // direction and would make layer order change as incidental backlinks are
    // loaded.
    if (relation.type === 'related') return
    outgoing.get(relation.source)!.push(relation.target)
    incoming.get(relation.target)!.push(relation.source)
  })

  const layers = new Map<string, number>()
  const remaining = new Map(ordered.map(item => [item.id, incoming.get(item.id)!.length]))
  const queue = ordered.filter(item => remaining.get(item.id) === 0).map(item => item.id)
  queue.forEach(id => layers.set(id, 0))
  for (let index = 0; index < queue.length; index += 1) {
    const id = queue[index]
    const nextLayer = (layers.get(id) || 0) + 1
    for (const child of outgoing.get(id) || []) {
      layers.set(child, Math.max(layers.get(child) ?? 0, nextLayer))
      const nextRemaining = (remaining.get(child) || 0) - 1
      remaining.set(child, nextRemaining)
      // A DAG node is enqueued only after every parent has been processed, so
      // a shared prerequisite cannot be assigned an order-dependent layer.
      if (nextRemaining === 0) queue.push(child)
    }
  }
  // A cycle or a disconnected component with only incoming edges gets a
  // deterministic fallback layer instead of an infinite traversal.
  ordered.forEach((item, index) => { if (!layers.has(item.id)) layers.set(item.id, index) })

  const grouped = new Map<number, KnowledgeItem[]>()
  ordered.forEach(item => {
    const layer = layers.get(item.id) || 0
    const list = grouped.get(layer) || []
    list.push(item)
    grouped.set(layer, list)
  })
  grouped.forEach(list => list.sort((left, right) => left.id.localeCompare(right.id)))

  const result: Record<string, StudyLayoutPosition> = {}
  const columnGap = 232
  const rowGap = 112
  const originX = 48
  const originY = 56
  grouped.forEach((list, layer) => list.forEach((item, row) => {
    const previous = preserved[item.id]
    result[item.id] = valid(previous)
      ? { x: previous.x, y: previous.y }
      : { x: originX + layer * columnGap, y: originY + row * rowGap }
  }))
  return result
}

export const STUDY_LAYOUT_LIMITS = {
  maxInteractiveNodes: 200,
  maxInteractiveEdges: 600,
  measuredMode: 'main-thread-bounded',
} as const
