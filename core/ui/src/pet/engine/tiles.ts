/**
 * 瓦片世界（体素化）：把桌面几何体素化成泰拉瑞亚式瓦片网格，
 * 寻路与移动决策全部落在瓦片上。
 *
 * user:"在设计方案中我们也说过体素化……不就是瓦片网格吗？所有的行为完全按照
 * 《泰拉瑞亚》去对齐，不用考虑既有实现……我的原意就是要让它跟泰拉瑞亚一样"+
 * (几何段（TerrainField）仍是物理碰撞的事实来源；本层把它们体素化成
 *  瓦片：实心 / 单向板 / 绳梯，寻路与行为决策只看瓦片——
 *  泰拉瑞亚：瓦片世界管逻辑，像素移动管表现。)
 *
 * 瓦片语义（对齐泰拉瑞亚）：
 * - Solid：四面阻挡。
 * - Platform：单向板——上方可站、从下可穿过、可下落穿过、水平可穿过。
 * - Ladder：绳梯——无碰撞，攀爬意图时抓附上下。
 */

// user:"通常泰拉瑞亚的瓦片力度有多细，这个就调成多细。之前的那个体素化可能不够细，
// 那你就当它是随便写的吧"+
// (对齐《泰拉瑞亚》的瓦片分辨率：16×16 像素一格。设计文档没有写死格宽，
//  之前的 48px 是实现自定值，不是设计；这里以泰拉瑞亚的 16px 为准。)
export const TILE_SIZE = 16

// 移动代价表（用户设计）：一瓦片 = 1；走=1、跳=x+y、爬=2、挂=3、落=(x+y)/2。
const WALK_COST = 1
const CLIMB_COST = 2
const HANG_COST = 3
const fallCost = (dc: number, dr: number): number => (Math.abs(dc) + Math.abs(dr)) / 2

export const enum TileType {
  Empty = 0,
  Solid = 1,
  Platform = 2,
  Ladder = 3,
}

export interface TileCell {
  col: number
  row: number
}

export interface TileGridOptions {
  /** 物理跳跃高度（像素）：判断跳跃边是否成立用真实高度，不用行差。 */
  jumpHeightPx: number
  /** 角色判定框宽/高（物理像素）：跳跃与落点的身体净空检查用。 */
  bodyWidth: number
  bodyHeight: number
  /** 走速与重力：跳跃边的水平射程按真实弹道算（不能只看跳格数）。 */
  walkSpeed: number
  gravity: number
}

export class TileGrid {
  readonly cols: number
  readonly rows: number
  readonly tiles: Uint8Array
  /** 建图参数：跳得上去的最大瓦片数（由物理跳跃高度换算）。 */
  readonly jumpTiles: number
  /** 物理跳跃高度（像素）：判断跳跃边是否成立用真实高度，不用行差。 */
  readonly jumpHeightPx: number
  /** 判定框占的瓦片数（高/半宽），净空检查用。 */
  readonly bodyTiles: number
  readonly bodyHalfCols: number
  /** 判定框像素尺寸（绳梯贴边抓附判定用）。 */
  readonly bodyWidth: number
  readonly bodyHeight: number
  readonly walkSpeed: number
  readonly gravity: number
  /** 每格正上方/正下方连续非实心瓦数（一次建图预计算，供 O(1) 净空判断）。 */
  private clearAboveCells: Uint16Array
  private clearBelowCells: Uint16Array
  version = -1

  constructor(readonly bounds: { x: number; y: number; width: number; height: number }, options: TileGridOptions) {
    this.cols = Math.max(1, Math.ceil(bounds.width / TILE_SIZE))
    this.rows = Math.max(1, Math.ceil(bounds.height / TILE_SIZE))
    this.tiles = new Uint8Array(this.cols * this.rows)
    this.jumpHeightPx = options.jumpHeightPx
    this.jumpTiles = Math.max(2, Math.floor(options.jumpHeightPx / TILE_SIZE))
    this.bodyTiles = Math.max(1, Math.ceil(options.bodyHeight / TILE_SIZE))
    this.bodyHalfCols = Math.max(0, Math.ceil(options.bodyWidth / 2 / TILE_SIZE))
    this.bodyWidth = options.bodyWidth
    this.bodyHeight = options.bodyHeight
    this.walkSpeed = options.walkSpeed
    this.gravity = options.gravity
    this.clearAboveCells = new Uint16Array(this.cols * this.rows)
    this.clearBelowCells = new Uint16Array(this.cols * this.rows)
  }

  index(col: number, row: number): number {
    return row * this.cols + col
  }

  inBounds(col: number, row: number): boolean {
    return col >= 0 && col < this.cols && row >= 0 && row < this.rows
  }

  typeAt(col: number, row: number): TileType {
    if (!this.inBounds(col, row)) return TileType.Solid
    return this.tiles[this.index(col, row)] as TileType
  }

  /** 世界坐标 → 瓦片列行。 */
  worldToCell(x: number, y: number): TileCell {
    return {
      col: Math.min(this.cols - 1, Math.max(0, Math.floor((x - this.bounds.x) / TILE_SIZE))),
      row: Math.min(this.rows - 1, Math.max(0, Math.floor((y - this.bounds.y) / TILE_SIZE))),
    }
  }

  /** 瓦片中心的世界坐标。 */
  cellCenter(col: number, row: number): { x: number; y: number } {
    return {
      x: this.bounds.x + (col + 0.5) * TILE_SIZE,
      y: this.bounds.y + (row + 0.5) * TILE_SIZE,
    }
  }

  /**
   * 体素化：把几何段烧进瓦片。
   * 横向平台段 → 一排 Platform（单向板）/ Solid（实心横边）；
   * 竖向段 → 一列 Ladder（绳梯）/ Solid（真墙）；
   * 斜坡段 → 沿线 Platform（楼梯——泰拉瑞亚玩家就用平台搭楼梯）。
   */
  build(terrain: { all(): Array<{ id: string; kind: string; layer: string; x1: number; y1: number; x2: number; y2: number; oneWay?: boolean; ladder?: boolean }> }): void {
    this.tiles.fill(TileType.Empty)
    const mark = (x1: number, y1: number, x2: number, y2: number, type: TileType): void => {
      const minX = Math.min(x1, x2)
      const maxX = Math.max(x1, x2)
      const minY = Math.min(y1, y2)
      const maxY = Math.max(y1, y2)
      const c0 = Math.min(this.cols - 1, Math.max(0, Math.floor((minX - this.bounds.x) / TILE_SIZE)))
      const c1 = Math.min(this.cols - 1, Math.max(0, Math.floor((maxX - this.bounds.x) / TILE_SIZE)))
      const r0 = Math.min(this.rows - 1, Math.max(0, Math.floor((minY - this.bounds.y) / TILE_SIZE)))
      const r1 = Math.min(this.rows - 1, Math.max(0, Math.floor((maxY - this.bounds.y) / TILE_SIZE)))
      for (let row = r0; row <= r1; row += 1) {
        for (let col = c0; col <= c1; col += 1) {
          const i = this.index(col, row)
          // 优先级：Solid > Platform > Ladder（实心最硬，单向板次之）。
          if (this.tiles[i] === TileType.Solid) continue
          if (this.tiles[i] === TileType.Platform && type === TileType.Ladder) continue
          this.tiles[i] = type
        }
      }
    }
    for (const segment of terrain.all()) {
      const horizontal = Math.abs(segment.y2 - segment.y1) <= Math.abs(segment.x2 - segment.x1)
      if (segment.kind === 'vertical') {
        mark(segment.x1, segment.y1, segment.x2, segment.y2, segment.ladder ? TileType.Ladder : TileType.Solid)
      } else if (segment.kind === 'ramp') {
        // 斜边=楼梯：沿线瓦片当平台走（物理仍按几何斜坡滑行）。
        const steps = Math.max(1, Math.ceil(Math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1) / TILE_SIZE))
        for (let index = 0; index <= steps; index += 1) {
          const t = index / steps
          mark(
            segment.x1 + (segment.x2 - segment.x1) * t,
            segment.y1 + (segment.y2 - segment.y1) * t,
            segment.x1 + (segment.x2 - segment.x1) * t + 1,
            segment.y1 + (segment.y2 - segment.y1) * t + 1,
            TileType.Platform,
          )
        }
      } else if (horizontal) {
        mark(segment.x1, segment.y1, segment.x2, segment.y2, segment.oneWay ? TileType.Platform : TileType.Solid)
      } else {
        mark(segment.x1, segment.y1, segment.x2, segment.y2, TileType.Solid)
      }
    }
    this.rebuildClearance()
  }

  /**
   * 预计算每格正上/正下方的连续非实心瓦数。
   *
   * user:"包括寻路，边，判定框全部都与泰拉瑞亚一致"+
   * (瓦片变细后，跳跃净空要按"身体高度 ÷ 格宽"算而不是固定看两格；
   *  逐格扫描在建图时一次算完，A* 里只做数组读取。)
   */
  private rebuildClearance(): void {
    const size = this.cols * this.rows
    this.clearAboveCells = new Uint16Array(size)
    this.clearBelowCells = new Uint16Array(size)
    for (let col = 0; col < this.cols; col += 1) {
      let above = 0
      for (let row = 0; row < this.rows; row += 1) {
        const i = this.index(col, row)
        this.clearAboveCells[i] = above
        above = this.tiles[i] === TileType.Solid ? 0 : above + 1
      }
      let below = 0
      for (let row = this.rows - 1; row >= 0; row -= 1) {
        const i = this.index(col, row)
        this.clearBelowCells[i] = below
        below = this.tiles[i] === TileType.Solid ? 0 : below + 1
      }
    }
  }

  /**
   * 站立瓦片：单向板瓦本身即支撑；空瓦需要下方有支撑（实心或单向板）。
   * 同时要求判定框放得下：屏幕顶边这类"脚底高于物理钳制线"或头顶没空间的
   * 瓦片不算可站——它们只提供悬挂/视觉边界，不产生"从天上走过去"的路。
   */
  isStandable(col: number, row: number): boolean {
    if (!this.inBounds(col, row)) return false
    const self = this.typeAt(col, row)
    const i = this.index(col, row)
    if (self === TileType.Platform) {
      if (this.standHeight(col, row) < this.bounds.y + this.bodyHeight) return false
      return this.clearAboveCells[i]! >= this.bodyTiles
    }
    if (self !== TileType.Empty) return false
    const below = this.typeAt(col, row + 1)
    if (below !== TileType.Solid && below !== TileType.Platform) return false
    if (this.standHeight(col, row) < this.bounds.y + this.bodyHeight) return false
    return this.clearAboveCells[i]! >= this.bodyTiles - 1
  }

  /** 檐下可挂瓦片：头顶是单向板、自身为空。 */
  isHangable(col: number, row: number): boolean {
    if (!this.inBounds(col, row)) return false
    return this.typeAt(col, row) === TileType.Empty && this.typeAt(col, row - 1) === TileType.Platform
  }

  isLadder(col: number, row: number): boolean {
    return this.typeAt(col, row) === TileType.Ladder
  }

  /**
   * 判定框是否与绳梯瓦重叠。
   * user:"L1墙可沿边缘攀爬，就像梯子"+
   * (屏幕边缘的绳梯在墙里，角色的中心被边界钳住进不去；只要身体贴到梯瓦
   *  就算抓附，因此按判定框覆盖的整块区域检查，而不是只看中心列。)
   */
  bodyTouchesLadder(x: number, y: number): boolean {
    const centerY = y - this.bodyHeight / 2
    const footRow = this.worldToCell(x, y - 1).row
    const centerRow = this.worldToCell(x, centerY).row
    const headRow = this.worldToCell(x, y - this.bodyHeight + 1).row
    const leftCol = this.worldToCell(x - this.bodyWidth / 2 + 1, centerY).col
    const rightCol = this.worldToCell(x + this.bodyWidth / 2 - 1, centerY).col
    for (const row of [footRow, centerRow, headRow]) {
      for (let col = leftCol; col <= rightCol; col += 1) {
        if (this.isLadder(col, row)) return true
      }
    }
    return false
  }

  /** 站立点的世界坐标：单向板瓦踩瓦顶面；空瓦踩下方支撑瓦的顶面。 */
  standPoint(col: number, row: number): { x: number; y: number } {
    return { x: this.bounds.x + (col + 0.5) * TILE_SIZE, y: this.standHeight(col, row) }
  }

  /**
   * 站立脚底高度（世界 y）。
   *
   * user:"包括寻路，边，判定框全部都与泰拉瑞亚一致"+
   * (单向板瓦的脚底在瓦顶（row 行上沿）；空瓦的脚底在下一行瓦顶。跳跃边必须
   *  用真实高差判断，否则"行差 5"会把 288px 的高台当成 240px 跳得上去。)
   */
  standHeight(col: number, row: number): number {
    return this.bounds.y + (this.typeAt(col, row) === TileType.Platform ? row : row + 1) * TILE_SIZE
  }

  /**
   * 自主探索的目的地：只有可站立点。
   *
   * user:"为什么它老要往上面跑"+"你这不又是在打补丁吗？……为什么悬挂点会评分更高"+
   * (悬挂是移动过程中的状态/手动指定的目标，不是"闲逛要去的地方"。之前把
   *  檐下悬挂点也塞进候选集，而屏幕顶边是一条连续的悬挂线——每列一个、
   *  整屏几十上百个，距离打分里它们自然占满"偏好距离"的那一圈，角色就
   *  反复爬到天花板来回挂。这不是给悬挂点扣分能解决的，是候选域本身就错了：
   *  目的地必须是能站的地方，悬挂只在 A* 的通行边里作为状态存在。)
   */
  standPoints(): Array<{ x: number; y: number; col: number; row: number }> {
    const points: Array<{ x: number; y: number; col: number; row: number }> = []
    for (let row = 0; row < this.rows; row += 1) {
      for (let col = 0; col < this.cols; col += 1) {
        if (!this.isStandable(col, row)) continue
        points.push({ ...this.standPoint(col, row), col, row })
      }
    }
    return points
  }

  /**
   * 泰拉瑞亚式瓦片 A*：走 / 跳（上 jumpTiles 内）/ 穿板下落 / 绳梯攀爬。
   * 返回瓦片路标序列（含起点与终点）。
   */
  findPath(fromX: number, fromY: number, toX: number, toY: number): TileCell[] | null {
    const start = this.startCell(fromX, fromY)
    const goal = this.goalCell(toX, toY)
    if (!start || !goal) return null

    const key = (col: number, row: number): number => this.index(col, row)
    const open: Array<{ col: number; row: number; g: number; f: number }> = [{ ...start, g: 0, f: this.heuristic(start.col, start.row, goal) }]
    const gScore = new Map<number, number>([[key(start.col, start.row), 0]])
    const cameFrom = new Map<number, number>()
    const closed = new Set<number>()
    let expansions = 0
    const maxExpansions = 8000

    while (open.length > 0 && expansions < maxExpansions) {
      open.sort((a, b) => a.f - b.f)
      const current = open.shift()!
      const ck = key(current.col, current.row)
      if (closed.has(ck)) continue
      closed.add(ck)
      expansions += 1
      if (current.col === goal.col && current.row === goal.row) {
        const cells: TileCell[] = []
        let cursor: number | undefined = ck
        while (cursor !== undefined) {
          cells.unshift({ col: cursor % this.cols, row: Math.floor(cursor / this.cols) })
          cursor = cameFrom.get(cursor)
        }
        return cells
      }
      for (const next of this.neighbours(current.col, current.row)) {
        const nk = key(next.col, next.row)
        if (closed.has(nk)) continue
        const tentative = current.g + next.cost
        if (tentative >= (gScore.get(nk) ?? Infinity)) continue
        gScore.set(nk, tentative)
        cameFrom.set(nk, ck)
        open.push({ col: next.col, row: next.row, g: tentative, f: tentative + this.heuristic(next.col, next.row, goal) })
      }
    }
    return null
  }

  /** 从某点出发有向可达的瓦片集合（不可达目标不被选中）。 */
  reachableTiles(x: number, y: number): Set<number> | null {
    const distances = this.reachableDistances(x, y)
    return distances ? new Set(distances.keys()) : null
  }

  /**
   * 从某点出发的最短"移动代价"图（瓦片代价单位，乘 TILE_SIZE ≈ 像素路程）。
   *
   * user:"那我问你，这个桌宠它站在最下边，凭什么会认为它离最上边这么更近？"+"改"+
   * (行为选靶原来用直线距离：天花板在 480px 外，正好接近"偏好距离"，
   *  就比 300px 外的地面点更"合适"——它根本没考虑爬上去要绕多远。
   *  这里用 A* 同一套边代价做 Dijkstra：爬一层就是一格一格走出来的路程，
   *  天花板再也不会被当成"附近的点"。)
   */
  reachableDistances(x: number, y: number): Map<number, number> | null {
    const start = this.startCell(x, y)
    if (!start) return null
    const distances = new Map<number, number>()
    const heap = new MinHeap<TileCell>()
    const startKey = this.index(start.col, start.row)
    distances.set(startKey, 0)
    heap.push(0, start)
    while (heap.size > 0) {
      const current = heap.pop()!
      const currentKey = this.index(current.value.col, current.value.row)
      if (current.cost > (distances.get(currentKey) ?? Infinity)) continue
      for (const next of this.neighbours(current.value.col, current.value.row, true)) {
        const cost = current.cost + next.cost
        const key = this.index(next.col, next.row)
        if (cost >= (distances.get(key) ?? Infinity)) continue
        distances.set(key, cost)
        heap.push(cost, { col: next.col, row: next.row })
      }
    }
    return distances
  }

  /** 起点瓦片：优先脚下站立的瓦片，找不到就向下/就近找站瓦。 */
  private startCell(x: number, y: number): TileCell | null {
    const cell = this.worldToCell(x, y)
    if (this.isStandable(cell.col, cell.row) || this.isLadder(cell.col, cell.row) || this.isHangable(cell.col, cell.row)) return cell
    for (let row = cell.row; row < this.rows; row += 1) {
      if (this.isStandable(cell.col, row)) return { col: cell.col, row }
    }
    return this.nearestStandable(cell.col, cell.row)
  }

  /** 终点瓦片：目标点附近最合适的站瓦（目标上方的空瓦、脚下有支撑）。 */
  private goalCell(x: number, y: number): TileCell | null {
    const cell = this.worldToCell(x, y)
    if (this.isStandable(cell.col, cell.row)) return this.normalizeStand(cell)
    if (this.isLadder(cell.col, cell.row)) return cell
    // 点击平台下沿：目标就是檐下悬挂点（可站也可挂）。
    if (this.isHangable(cell.col, cell.row)) return cell
    for (let dy = 0; dy <= 2; dy += 1) {
      if (this.isStandable(cell.col, cell.row + dy)) return this.normalizeStand({ col: cell.col, row: cell.row + dy })
    }
    return this.nearestStandable(cell.col, cell.row)
  }

  /**
   * 单向板顶的"板瓦"与"板上空瓦"是同一个站立点（脚底同高）；
   * 统一归一化成板瓦，路标才能接上绳梯与同行行走链。
   */
  private normalizeStand(cell: TileCell): TileCell {
    if (this.typeAt(cell.col, cell.row) === TileType.Empty
      && this.typeAt(cell.col, cell.row + 1) === TileType.Platform) {
      return { col: cell.col, row: cell.row + 1 }
    }
    return cell
  }

  private nearestStandable(col: number, row: number): TileCell | null {
    for (let radius = 1; radius <= Math.max(this.cols, this.rows); radius += 1) {
      for (let dr = -radius; dr <= radius; dr += 1) {
        for (let dc = -radius; dc <= radius; dc += 1) {
          if (Math.abs(dc) !== radius && Math.abs(dr) !== radius) continue
          if (this.isStandable(col + dc, row + dr)) return this.normalizeStand({ col: col + dc, row: row + dr })
        }
      }
    }
    return null
  }

  private heuristic(col: number, row: number, goal: TileCell): number {
    // 最小边价是"落下"的 0.5/格；启发式必须不高估真实代价，否则 A* 会提前收工。
    return (Math.abs(col - goal.col) + Math.abs(row - goal.row)) * 0.5
  }

  /**
   * 查询一条实际存在的移动边的代价（调试/验收用）。
   *
   * user:"一瓦片为1，行走时权重为1 跳跃为x+y合。攀爬时的价为行走时的2倍，
   * 悬挂时的价为行走时的3倍，落下价为x+y的一半"+
   * (A* 的边代价严格按这张表；返回 null 表示两个格子之间没有合法移动边。)
   */
  moveCost(from: TileCell, to: TileCell): number | null {
    const found = this.neighbours(from.col, from.row).find(
      candidate => candidate.col === to.col && candidate.row === to.row,
    )
    return found ? found.cost : null
  }

  /**
   * 泰拉瑞亚 NPC 移动规则：走、跳（上 jumpTiles 内）、穿板下落/走落、绳梯攀爬。
   */
  private neighbours(col: number, row: number, reachability = false): Array<{ col: number; row: number; cost: number }> {
    const result: Array<{ col: number; row: number; cost: number }> = []
    const standing = this.isStandable(col, row)
    const onLadder = this.isLadder(col, row)
    const hangable = this.isHangable(col, row)

    if (onLadder) {
      // 绳梯：沿梯上下（攀爬价 = 行走 ×2），梯口横移按行走价。
      for (const dr of [-1, 1]) {
        if (this.isLadder(col, row + dr) || this.isStandable(col, row + dr)) {
          result.push({ col, row: row + dr, cost: CLIMB_COST })
        }
      }
      for (const dc of [-1, 1]) {
        if (this.isStandable(col + dc, row) || this.isLadder(col + dc, row)) {
          result.push({ col: col + dc, row, cost: WALK_COST })
        }
        // 梯子顶端横跨到檐下：屏幕顶边的悬挂点只能从边缘绳梯过去。
        if (this.isHangable(col + dc, row)) result.push({ col: col + dc, row, cost: HANG_COST })
      }
      return result
    }

    if (hangable) {
      // 檐下：沿同一檐滑行（悬挂价 = 行走 ×3）；向下松手按落下价。
      for (const dc of [-1, 1]) {
        if (this.isHangable(col + dc, row)) result.push({ col: col + dc, row, cost: HANG_COST })
        if (this.isStandable(col + dc, row)) result.push({ col: col + dc, row, cost: HANG_COST })
        if (this.isLadder(col + dc, row)) result.push({ col: col + dc, row, cost: HANG_COST })
      }
      const below = this.firstStandableBelow(col, row)
      if (below) {
        result.push({ col: below.col, row: below.row, cost: fallCost(below.col - col, below.row - row) })
      }
      return result
    }

    if (!standing) return result

    // 平地行走。
    for (const dc of [-1, 1]) {
      if (this.isStandable(col + dc, row)) result.push({ col: col + dc, row, cost: WALK_COST })
    }
    // 抓住相邻绳梯（走过绳子即抓住——泰拉瑞亚绳子语义）。
    for (const dc of [-1, 1]) {
      if (this.isLadder(col + dc, row)) result.push({ col: col + dc, row, cost: WALK_COST })
    }
    if (this.isLadder(col, row - 1) || this.isLadder(col, row + 1)) {
      result.push({ col, row: row + (this.isLadder(col, row - 1) ? -1 : 1), cost: CLIMB_COST })
    }
    // 跳上去：jumpTiles 内、上方走廊通畅的目标站瓦。
    const fromHeight = this.standHeight(col, row)
    // 可达性预筛只要小跳（行为选靶用）；精确寻路才枚举全射程跳跃。
    const maxDx = reachability ? Math.min(3, this.jumpTiles) : this.jumpTiles
    const maxDy = reachability ? Math.min(4, this.jumpTiles) : this.jumpTiles
    for (let dy = 1; dy <= maxDy; dy += 1) {
      for (let dx = -maxDx; dx <= maxDx; dx += 1) {
        if (dx === 0 && dy === 1) continue
        const target = { col: col + dx, row: row - dy }
        if (!this.isStandable(target.col, target.row)) continue
        // 真实高差必须落在一次跳跃能到的高度内（瓦片行差 ≠ 脚底高差）。
        const rise = fromHeight - this.standHeight(target.col, target.row)
        if (rise < TILE_SIZE * 0.5 || rise > this.jumpHeightPx + 1) continue
        // 水平射程按真实弹道算：起跳速度 v=√(2gh)，落地时刻取大根，
        // 射程 = 走速 × 滞空时间。跳得更高时滞空更短，不能一律按 16 格。
        const impulse = Math.sqrt(2 * this.gravity * this.jumpHeightPx)
        const airTime = (impulse + Math.sqrt(Math.max(0, impulse * impulse - 2 * this.gravity * rise))) / this.gravity
        const maxDx = Math.max(1, Math.floor((this.walkSpeed * airTime) / TILE_SIZE))
        if (Math.abs(dx) > maxDx) continue
        if (!this.jumpCorridorClear(col, row, target.col, target.row, rise)) continue
        // 跳跃价 = 水平格数 + 竖直格数（x + y）。
        result.push({ col: target.col, row: target.row, cost: Math.abs(dx) + dy })
      }
    }
    // 下落/穿板：左右邻列向下找第一个站瓦（走落边缘或穿单向板下落）。
    for (const dc of [-1, 1]) {
      const below = this.firstStandableBelow(col + dc, row)
      if (below && below.row > row) {
        result.push({ col: below.col, row: below.row, cost: fallCost(below.col - col, below.row - row) })
      }
    }
    // 正下方穿板：脚下是单向板时可垂直下落。
    if (this.typeAt(col, row + 1) === TileType.Platform) {
      const below = this.firstStandableBelow(col, row + 1)
      if (below) result.push({ col: below.col, row: below.row, cost: fallCost(below.col - col, below.row - row) })
    }
    // 檐下抓挂：头顶平台且自身可站时，向上跳抓檐（可挂）。
    if (this.isHangable(col, row - 1)) {
      result.push({ col, row: row - 1, cost: HANG_COST })
    }
    return result
  }

  /** 起跳走廊检查：出发瓦上方两格与目标瓦上方的竖直空间必须可通。 */
  /**
   * 起跳走廊 + 落点身体净空检查（瓦片变细后按"身体占几格"计算）。
   * 起跳点上方要留出身体高度 + 起跳高度；落点及其身体宽度范围内要能站得下。
   */
  private jumpCorridorClear(col: number, row: number, targetCol: number, targetRow: number, rise: number): boolean {
    const riseCells = Math.ceil(rise / TILE_SIZE)
    const startIndex = this.inBounds(col, row) ? this.index(col, row) : -1
    if (startIndex < 0) return false
    if (this.clearAboveCells[startIndex]! < this.bodyTiles - 1 + riseCells) return false
    const targetType = this.typeAt(targetCol, targetRow)
    const needed = targetType === TileType.Platform ? this.bodyTiles : this.bodyTiles - 1
    for (let c = targetCol - this.bodyHalfCols; c <= targetCol + this.bodyHalfCols; c += 1) {
      if (!this.inBounds(c, targetRow)) return false
      if (this.clearAboveCells[this.index(c, targetRow)]! < needed) return false
    }
    const step = Math.sign(targetCol - col) || 1
    for (let c = col + step; c !== targetCol + step; c += step) {
      if (!this.inBounds(c, targetRow)) return false
      if (this.typeAt(c, targetRow) === TileType.Solid) return false
      if (this.typeAt(c, targetRow - 1) === TileType.Solid) return false
    }
    return true
  }

  /** 向下找第一个站瓦（含穿过多层单向板）。 */
  private firstStandableBelow(col: number, row: number): TileCell | null {
    for (let r = row + 1; r < this.rows; r += 1) {
      const type = this.typeAt(col, r)
      if (type === TileType.Solid) return this.isStandable(col, r - 1) ? { col, row: r - 1 } : null
      if (this.isStandable(col, r)) return { col, row: r }
    }
    return null
  }
}

/** 最小堆：Dijkstra 用（格子数量有限，但线性扫描会拖慢选靶）。 */
class MinHeap<T> {
  private items: Array<{ cost: number; value: T }> = []

  get size(): number {
    return this.items.length
  }

  push(cost: number, value: T): void {
    const items = this.items
    items.push({ cost, value })
    let index = items.length - 1
    while (index > 0) {
      const parent = (index - 1) >> 1
      if (items[parent]!.cost <= items[index]!.cost) break
      ;[items[parent], items[index]] = [items[index]!, items[parent]!]
      index = parent
    }
  }

  pop(): { cost: number; value: T } | undefined {
    const items = this.items
    if (items.length === 0) return undefined
    const top = items[0]!
    const last = items.pop()!
    if (items.length === 0) return top
    items[0] = last
    let index = 0
    for (;;) {
      const left = index * 2 + 1
      const right = left + 1
      let smallest = index
      if (left < items.length && items[left]!.cost < items[smallest]!.cost) smallest = left
      if (right < items.length && items[right]!.cost < items[smallest]!.cost) smallest = right
      if (smallest === index) break
      ;[items[smallest], items[index]] = [items[index]!, items[smallest]!]
      index = smallest
    }
    return top
  }
}
