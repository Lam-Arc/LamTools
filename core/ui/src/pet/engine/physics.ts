/**
 * 物理：泰拉瑞亚式瓦片物理。
 *
 * user:"包括寻路，边，判定框全部都与泰拉瑞亚一致，先一致，再适配"+
 * "所有的行为完全按照《泰拉瑞亚》去对齐，不用考虑既有实现"+
 * (实体是瓦片尺寸的 AABB 判定框（泰拉瑞亚玩家 1.25×2.625 格）；
 *  碰撞 = AABB 对瓦片网格的分轴扫掠：实心瓦四面阻挡、单向板只挡自上而下的
 *  下落（可从下穿过、可下落穿过）、绳梯无碰撞只供攀爬；
 *  移动 = 意图（走/跳/下落/爬/挂）+ 重力积分 + 瓦片解算，固定步长。)
 */
import { TileGrid, TileType, TILE_SIZE } from './tiles.ts'

export const PHYSICS_STEP = 1 / 120

type Vec2 = { x: number; y: number }

export interface PhysicsConfig {
  /** 判定框宽（泰拉瑞亚玩家 = 1.25 格）。 */
  hitboxWidth: number
  /** 判定框高（泰拉瑞亚玩家 = 2.625 格）。 */
  hitboxHeight: number
  gravity: number
  maxFallSpeed: number
  walkSpeed: number
  jumpImpulse: number
  climbSpeed: number
  hangSpeed: number
  /** 空中水平操控系数（泰拉瑞亚空中操控弱于地面）。 */
  airControl: number
  /** 地面加速度。 */
  accel: number
  /** 下落穿透单向板的窗口时长（秒）。 */
  dropThroughTime: number
}

export const DEFAULT_PHYSICS: PhysicsConfig = {
  // 判定框尺寸 = 角色在屏幕上的大小（物理像素），不随瓦片粒度变化：
  // 瓦片只管地形分辨率，收细到 16px 后角色仍是 60×120 的 AABB（约 3.75×7.5 格）。
  hitboxWidth: 60,
  hitboxHeight: 120,
  gravity: 2400,
  maxFallSpeed: 2600,
  walkSpeed: 260,
  // 跳高 ≈ 261px ≈ 5.4 格（泰拉瑞亚基础跳约 5 格量级）。
  jumpImpulse: 1120,
  climbSpeed: 190,
  hangSpeed: 150,
  airControl: 0.45,
  accel: 25000,
  dropThroughTime: 0.25,
}

export type MotionContact = 'none' | 'ground' | 'ceiling' | 'ladder'

export interface MotionIntent {
  /** 目标水平速度（正右负左）。 */
  vx?: number
  /** 本步请求一次跳跃冲量。 */
  jump?: boolean
  /** 站在单向板上请求下落穿过。 */
  dropThrough?: boolean
  /** 沿绳梯攀爬方向：-1 上，1 下，0 停。 */
  climb?: -1 | 0 | 1
  /** 请求抓挂（跳向檐下时向上顶头吸附）。 */
  hang?: boolean
  /** 松开悬挂（保留当前速度）。 */
  release?: boolean
  /** 抓取时的弹簧目标点。 */
  dragTarget?: Vec2 | null
  /**
   * 穿越地形（用户拖拽）。
   * user:"我拖住桌宠的时候，不应该有任何一个除了屏幕（也就是 L0 级）的墙壁会挡住它"+
   * (拖拽主控期间只受屏幕边界钳制；窗口/手绘线/绳梯等一律不挡。)
   */
  ghost?: boolean
}

export interface BodyState {
  /** 脚底中心（判定框底边中点），物理像素。 */
  x: number
  y: number
  vx: number
  vy: number
  width: number
  height: number
  contact: MotionContact
  grounded: boolean
  /** 正在绳梯上。 */
  climbing: boolean
  /** 已吸附在平台下沿（可挂）。 */
  hung: boolean
  /** 下落穿透单向板的剩余时间。 */
  dropTimer: number
  /** 主动松手后的吸附冷却（秒）：防止刚松手就被同一块板重新吸住。 */
  hangCooldown: number
  /** 最近一次落地/离地的物理阶段，供动画同步。 */
  phase: 'idle' | 'rising' | 'apex' | 'falling' | 'landed'
}

export interface StepEvents {
  landed: boolean
  jumped: boolean
  hung: boolean
  released: boolean
}

export function createBody(x: number, y: number, config: PhysicsConfig): BodyState {
  return {
    x,
    y,
    vx: 0,
    vy: 0,
    width: config.hitboxWidth,
    height: config.hitboxHeight,
    contact: 'none',
    grounded: false,
    climbing: false,
    hung: false,
    dropTimer: 0,
    hangCooldown: 0,
    phase: 'falling',
  }
}

/** AABB 的四至（世界坐标）。 */
export function bodyBounds(body: BodyState): { left: number; right: number; top: number; bottom: number } {
  return {
    left: body.x - body.width / 2,
    right: body.x + body.width / 2,
    top: body.y - body.height,
    bottom: body.y,
  }
}

/** 该瓦片对这个实体是否构成水平/向上阻挡（单向板与绳梯不挡横移与上升）。 */
function blocksMotion(grid: TileGrid, col: number, row: number, body: BodyState, dropTimer: number, forVertical: boolean, movingDown: boolean): boolean {
  const type = grid.typeAt(col, row)
  if (type === TileType.Solid) return true
  if (type === TileType.Platform) {
    // 单向板只在"下落穿过"时阻挡；下落穿透窗口期内完全透明。
    return forVertical && movingDown && dropTimer <= 0
  }
  void body
  return false
}

/**
 * 推进一个固定步：意图 → 速度 → 分轴移动 → 瓦片解算。
 * 返回本步发生的物理事件；调用方据此同步动画阶段。
 */
export function stepBody(
  body: BodyState,
  intent: MotionIntent,
  config: PhysicsConfig,
  grid: TileGrid,
  dt: number,
): StepEvents {

  const events: StepEvents = { landed: false, jumped: false, hung: false, released: false }
  const wasGrounded = body.grounded
  if (body.hangCooldown > 0) body.hangCooldown = Math.max(0, body.hangCooldown - dt)
  // 用户拖住时立刻脱离攀爬/悬挂：拖拽是最高控制权，不能被梯子/檐口拽住。
  if (intent.dragTarget) {
    body.climbing = false
    body.hung = false
  }

  // 1) 绳梯：身体与绳梯瓦片重叠且有攀爬意图 → 攀爬态（重力暂停）。
  const footCell = grid.worldToCell(body.x, body.y - 1)
  const centerCell = grid.worldToCell(body.x, body.y - body.height / 2)
  // user:"竖边就像泰拉瑞亚里的绳子一样，或者说是《MC》里的梯子一样"+
  // (绳梯穿过窗口顶的单向板时，板瓦本身盖掉了绳梯瓦；向上爬经过板瓦这一段
  //  仍算抓附，才能爬过板顶站上去。)
  // 脚所在的那一格是单向板、下面接着绳梯：绳子从板顶穿下来的最后一段。
  // 用 body.y（脚所在格）而不是 y-1（脚上方格），否则差 1px 就丢抓附。
  const feetCell = grid.worldToCell(body.x, body.y)
  const ropeThroughPlatform = (intent.climb ?? 0) < 0
    && grid.typeAt(feetCell.col, feetCell.row) === TileType.Platform
    && grid.isLadder(feetCell.col, feetCell.row + 1)
  // 身体贴到绳梯即可抓附（屏幕边缘的梯子在墙里，中心进不去）。
  const touchingLadder = grid.bodyTouchesLadder(body.x, body.y) || ropeThroughPlatform
  if (!body.climbing && intent.climb !== undefined && touchingLadder) {
    body.climbing = true
    body.hung = false
    body.grounded = false
  }
  if (body.climbing && (!touchingLadder || intent.climb === undefined)) {
    body.climbing = false
    // 离开绳梯时清掉攀爬速度：爬速不是弹道，不该把角色甩向天花板。
    body.vy = 0
  }
  if (body.climbing) {
    const climb = intent.climb ?? 0
    body.vy = climb * config.climbSpeed
    body.vx = intent.vx !== undefined ? intent.vx * 0.5 : 0
    body.x += body.vx * dt
    body.y += body.vy * dt
    body.grounded = false
    body.contact = 'ladder'
    body.phase = body.vy < 0 ? 'rising' : body.vy > 0 ? 'falling' : 'idle'
    clampToGrid(body, grid)
    // 攀爬中落到地面：地面必须从"脚下这一行"向下找，
    // 否则天花板瓦（L1:top 平台）会被当成地面，宠物被瞬移到屏幕顶。
    if (body.y >= groundLineBelow(grid, body.x, grid.worldToCell(body.x, body.y).row) && body.vy > 0) {
      body.y = groundLineBelow(grid, body.x, grid.worldToCell(body.x, body.y).row)
      body.vy = 0
      body.grounded = true
      body.climbing = false
      body.contact = 'ground'
      events.landed = true
      body.phase = 'landed'
    }
    return events
  }

  // 2) 悬挂（挂在单向板下沿）：沿板底滑行，松手或目标在下方时脱落。
  if (body.hung) {
    if (intent.release) {
      body.hung = false
      // 松手后短暂禁止再吸附：否则同一帧内 head 还在板下，会被重新抓住。
      body.hangCooldown = 0.35
      events.released = true
      // 松手保留水平速度，自由落体。
    } else {
      const slide = Math.max(-config.hangSpeed, Math.min(config.hangSpeed, intent.vx ?? 0))
      body.vx = slide
      body.vy = 0
      body.x += body.vx * dt
      body.y = body.y
      body.grounded = false
      body.contact = 'ceiling'
      body.phase = 'idle'
      // 头顶不再是单向板 → 自然脱落（滑出板边）。
      const head = grid.worldToCell(body.x, body.y - body.height - 2)
      if (grid.typeAt(head.col, head.row) !== TileType.Platform) {
        body.hung = false
        events.released = true
      }
      return events
    }
  }

  // 3) 抓取：弹性牵引（用户主控，仍受瓦片碰撞）。
  if (intent.dragTarget) {
    const stiffness = 26
    const damping = 7.5
    const ax = (intent.dragTarget.x - body.x) * stiffness - body.vx * damping
    const ay = (intent.dragTarget.y - body.y) * stiffness - body.vy * damping
    body.vx += ax * dt
    body.vy += ay * dt
    const speed = Math.hypot(body.vx, body.vy)
    const maxSpeed = 3200
    if (speed > maxSpeed) {
      body.vx *= maxSpeed / speed
      body.vy *= maxSpeed / speed
    }
  } else {
    // 4) 水平意图 → 速度（地面全加速、空中部分操控）。
    if (intent.vx !== undefined) {
      const control = body.grounded ? 1 : config.airControl
      const delta = intent.vx - body.vx
      const maxDelta = config.accel * control * dt
      body.vx += Math.max(-maxDelta, Math.min(maxDelta, delta))
    }
    // 跳跃：在既有速度上叠加冲量。
    if (intent.jump && body.grounded) {
      body.vy -= config.jumpImpulse
      events.jumped = true
      body.grounded = false
      body.phase = 'rising'
    }
    // 下落穿透窗口计时。
    if (body.dropTimer > 0) body.dropTimer = Math.max(0, body.dropTimer - dt)
    if (intent.dropThrough && body.grounded) {
      // user:"平台可上也可下"+(站在单向板上提交下落：短暂无视单向板，穿下去。)
      body.dropTimer = config.dropThroughTime
      body.grounded = false
    }
    // 重力。
    body.vy = Math.min(body.vy + config.gravity * dt, config.maxFallSpeed)
  }

  // 5) 分轴移动 + 瓦片解算。
  moveX(body, body.vx * dt, config, grid, !!intent.ghost)
  const landed = moveY(body, body.vy * dt, config, grid, intent, events)

  // 6) 绳梯吸附（攀爬意图 + 与绳梯重叠）。
  if (intent.climb !== undefined && !body.climbing) {
    if (grid.bodyTouchesLadder(body.x, body.y)) body.climbing = true
  }

  // 7) 抓挂：头顶贴到单向板下沿 → 吸附。
  // user:"L1顶部那一条是可以悬挂的"+
  // (从梯顶横移到檐下时角色已停在屏幕钳制线，竖直速度是 0；只要头已贴板
  //  或还在上升就允许吸附，不再死磕 vy<0。)
  if (intent.hang && !body.hung && body.hangCooldown <= 0) {
    const headCell = grid.worldToCell(body.x, body.y - body.height - 2)
    if (grid.typeAt(headCell.col, headCell.row) === TileType.Platform) {
      const hangY = (headCell.row + 1) * TILE_SIZE + grid.bounds.y + body.height
      if (body.vy < 0 || Math.abs(body.y - hangY) < 40) {
        body.hung = true
        body.hangCooldown = 0
        body.vy = 0
        body.y = hangY
        body.contact = 'ceiling'
        events.hung = true
        body.phase = 'idle'
      }
    }
  }

  // 8) 相位（动画跟随物理）。
  if (body.grounded) {
    body.phase = events.landed ? 'landed' : 'idle'
  } else if (body.vy < -40) {
    body.phase = 'rising'
  } else if (Math.abs(body.vy) <= 40) {
    body.phase = 'apex'
  } else {
    body.phase = 'falling'
  }
  void wasGrounded
  void landed
  clampToGrid(body, grid)
  return events
}

function clampToGrid(body: BodyState, grid: TileGrid): void {
  const half = body.width / 2
  const minX = grid.bounds.x + half
  const maxX = grid.bounds.x + grid.bounds.width - half
  if (body.x < minX) { body.x = minX; if (body.vx < 0) body.vx = 0 }
  if (body.x > maxX) { body.x = maxX; if (body.vx > 0) body.vx = 0 }
  const minY = grid.bounds.y + body.height
  if (body.y < minY) { body.y = minY; if (body.vy < 0) body.vy = 0 }
  const maxY = grid.bounds.y + grid.bounds.height
  if (body.y > maxY) {
    body.y = maxY
    if (body.vy > 0) body.vy = 0
    body.grounded = true
    body.contact = 'ground'
  }
}

/** 水平移动 + 实心瓦解算（单向板/绳梯不挡横移——泰拉瑞亚平台可水平穿过）。 */
function moveX(body: BodyState, dx: number, config: PhysicsConfig, grid: TileGrid, ghost = false): void {
  if (ghost) {
    // 拖拽主控：直接位移，地形不参与，屏幕边界由末尾的 clampToGrid 负责。
    body.x += dx
    return
  }
  const half = body.width / 2
  let newX = body.x + dx
  const top = body.y - body.height + 2
  const bottom = body.y - 2
  if (dx !== 0) {
    const direction = Math.sign(dx)
    const leadingEdge = direction > 0 ? newX + half : newX - half
    const col = grid.worldToCell(leadingEdge, body.y).col
    const rowStart = grid.worldToCell(0, top).row
    const rowEnd = grid.worldToCell(0, bottom).row
    let blocked = false
    for (let row = rowStart; row <= rowEnd; row += 1) {
      if (grid.typeAt(col, row) === TileType.Solid) { blocked = true; break }
    }
    if (blocked) {
      newX = direction > 0
        ? grid.bounds.x + col * TILE_SIZE - half - 0.01
        : grid.bounds.x + (col + 1) * TILE_SIZE + half + 0.01
      body.vx = 0
    }
  }
  body.x = newX
  void config
}

/** 垂直移动 + 瓦片解算：下落落在实心/单向板顶（可穿板窗口内跳过单向板），上升顶实心。 */
function moveY(
  body: BodyState,
  dy: number,
  config: PhysicsConfig,
  grid: TileGrid,
  intent: MotionIntent,
  events: StepEvents,
): boolean {
  let landed = false
  if (intent.ghost) {
    // 拖拽主控：上下也不碰瓦片（可把桌宠拖到窗口上方/下方），只留屏幕钳制。
    body.y += dy
    body.grounded = false
    body.contact = 'none'
    return false
  }
  const half = body.width / 2
  let newY = body.y + dy
  const left = body.x - half + 2
  const right = body.x + half - 2
  const colStart = grid.worldToCell(left, body.y).col
  const colEnd = grid.worldToCell(right, body.y).col

  if (dy >= 0) {
    // 下落：脚底扫过的行里找第一块可落瓦（实心 / 未被穿透窗口豁免的单向板）。
    const prevBottom = body.y
    const newBottom = newY
    const rowStart = grid.worldToCell(0, prevBottom).row
    const rowEnd = grid.worldToCell(0, newBottom).row
    let landingRow = -1
    for (let row = rowStart; row <= rowEnd; row += 1) {
      const tileTop = grid.bounds.y + row * TILE_SIZE
      if (prevBottom > tileTop + 0.01) continue
      let solid = false
      for (let col = colStart; col <= colEnd; col += 1) {
        const type = grid.typeAt(col, row)
        if (type === TileType.Solid || (type === TileType.Platform && body.dropTimer <= 0)) { solid = true; break }
      }
      if (solid) { landingRow = row; break }
    }
    if (landingRow >= 0) {
      newY = grid.bounds.y + landingRow * TILE_SIZE
      if (body.vy > 60) events.landed = true
      body.vy = 0
      body.grounded = true
      body.contact = 'ground'
      landed = true
    } else {
      body.grounded = false
      body.contact = 'none'
    }
  } else {
    // 上升：头顶扫过行里撞实心瓦（单向板可穿过——泰拉瑞亚语义）。
    const prevTop = body.y - body.height
    const newTop = newY - body.height
    const rowStart = grid.worldToCell(0, prevTop).row
    const rowEnd = grid.worldToCell(0, newTop).row
    for (let row = rowStart; row >= rowEnd; row -= 1) {
      let solid = false
      for (let col = colStart; col <= colEnd; col += 1) {
        if (grid.typeAt(col, row) === TileType.Solid) { solid = true; break }
      }
      if (solid) {
        newY = grid.bounds.y + (row + 1) * TILE_SIZE + body.height
        body.vy = 0
        body.contact = 'ceiling'
        break
      }
    }
    body.grounded = false
    body.contact = body.contact === 'ceiling' ? 'ceiling' : 'none'
  }
  body.y = newY
  void intent
  return landed
}

/** 某竖直线上、从 fromRow 起向下最近的地表高度（攀爬落地用）。 */
function groundLineBelow(grid: TileGrid, x: number, fromRow: number): number {
  const col = grid.worldToCell(x, grid.bounds.y + 1).col
  for (let row = Math.max(0, fromRow); row < grid.rows; row += 1) {
    if (grid.typeAt(col, row) === TileType.Solid || grid.typeAt(col, row) === TileType.Platform) {
      return grid.bounds.y + row * TILE_SIZE
    }
  }
  return grid.bounds.y + grid.bounds.height
}

export function speed(body: BodyState): number {
  return Math.hypot(body.vx, body.vy)
}
