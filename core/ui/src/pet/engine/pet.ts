/**
 * 一只桌宠的运行时实例。
 *
 * 组合关系：物理（瓦片 AABB 判定框 + 重力积分）+ Action 执行器 + 泰拉瑞亚式
 * 瓦片寻路跟随 + 自主行为 + 精灵帧。
 *
 * user:"包括寻路，边，判定框全部都与泰拉瑞亚一致，先一致，再适配"+
 * (判定框 = 瓦片尺寸的 AABB；移动决策 = 沿瓦片路标走/跳/下落/攀爬/挂，
 *  泰拉瑞亚 NPC 语义：路走不通就重新寻路，卡住由看门狗兜底。)
 */
import { ActionExecutor, ActionRegistry, buildDefaultActions, type ActionContext } from './actions.ts'
import { BehaviorController, type BehaviorConfig } from './behavior.ts'
import { clamp, distance, type Vec2 } from './math.ts'
import { DEFAULT_PHYSICS, PHYSICS_STEP, createBody, stepBody, type BodyState, type PhysicsConfig, type StepEvents } from './physics.ts'
import { TILE_SIZE, type TileCell, type TileGrid } from './tiles.ts'
import {
  defaultHitboxes,
  frameAt,
  hitTest,
  hitboxWorldRect,
  spriteRect,
  type AnimationMap,
  type ClipGeometry,
  type FrameRef,
  type PetClip,
  type PetHitbox,
} from './sprite.ts'
import type { TerrainField } from './terrain.ts'

export interface PetInstanceSettings {
  id: string
  name: string
  packId?: string
  scale: number
  facing: 1 | -1
  radius: number
  physics: Partial<PhysicsConfig>
  behavior: Partial<BehaviorConfig>
  hitboxes: PetHitbox[]
  /** actionId → 动画资源；缺资源的动作仍然能跑物理。 */
  actions: AnimationMap
  /** 精灵尺寸（物理像素），由资源加载后回填。 */
  spriteWidth: number
  spriteHeight: number
  visible: boolean
  /** 右键临时会话切换：重启后必须回到持久默认。 */
  zOffset?: number
}

export interface PetTickContext {
  now: number
  dtMs: number
  terrain: TerrainField
  tiles: TileGrid
  mouse: Vec2 | null
  /** 用户抓取中：自主行为不得抢控制权。 */
  dragging: boolean
}

export interface PetRenderState {
  id: string
  name: string
  /** 精灵绘制矩形（脚底锚定、含视觉缩放）。 */
  rect: { x: number; y: number; width: number; height: number }
  /** 判定框（泰拉瑞亚式 AABB，物理像素）。 */
  box: { x: number; y: number; width: number; height: number }
  frame: FrameRef | null
  facing: 1 | -1
  actionId: string | null
  visible: boolean
  dragging: boolean
  velocity: Vec2
  phase: BodyState['phase']
  hitboxes: PetHitbox[]
  spriteWidth: number
  spriteHeight: number
  scale: number
  /** 当前动作已播放时长（毫秒）：2D 取帧、3D 推 mixer 都靠它。 */
  elapsedMs: number
  /** 当前动作绑定的资源；null 表示缺资源，渲染层用占位。 */
  clip: PetClip | undefined
}

export interface PetDiagnostics {
  id: string
  actionId: string | null
  actionLabel: string
  transition: string
  grounded: boolean
  hung: boolean
  climbing: boolean
  velocity: Vec2
  position: Vec2
  pathNodes: number
  pathIndex: number
  goal: Vec2 | null
  behavior: string
  missingAnimation: string | null
}

export class PetInstance {
  readonly id: string
  name: string
  readonly settings: PetInstanceSettings
  readonly body: BodyState
  readonly physics: PhysicsConfig
  readonly registry: ActionRegistry
  readonly executor: ActionExecutor
  readonly behavior: BehaviorController
  facing: 1 | -1
  visible: boolean
  /** 精灵帧计时。 */
  private spriteElapsed = 0
  private accumulator = 0
  private dragTarget: Vec2 | null = null
  /** 抓起时鼠标相对脚底的位置：拖拽保持这个偏移，角色不会跳到光标上。 */
  private dragOffset: Vec2 = { x: 0, y: 0 }
  private userDragging = false
  /** 有待用户处理的审批/提问：停止自主移动，原地待机（疑问动作）。 */
  private attentionHold = false
  private goal: Vec2 | null = null
  private goalIsUser = false
  /** 瓦片路标序列（泰拉瑞亚式寻路结果）。 */
  private tilePath: TileCell[] | null = null
  private tileIndex = 0
  /** 下行路标：站在单向板上时提交下落意图。 */
  private dropIntent = false
  /** 沿路径行走却长时间无水平位移的累计时长（卡住看门狗）。 */
  private stuckForMs = 0
  /** 上次因卡住而重寻路的时间，至少间隔 1 秒防抖。 */
  private lastStuckReplanAt = 0
  private lastPlan: 'ok' | 'unreachable' | null = null
  private lastEvents: StepEvents | null = null
  private lastNow = 0
  private home: Vec2

  constructor(settings: PetInstanceSettings, spawn: Vec2) {
    this.id = settings.id
    this.name = settings.name
    this.settings = settings
    this.physics = { ...DEFAULT_PHYSICS, ...settings.physics }
    this.body = createBody(spawn.x, spawn.y, this.physics)
    this.registry = new ActionRegistry()
    this.registry.registerAll(buildDefaultActions())
    // 角色可以注册额外动作，不需要改物理或寻路。
    this.executor = new ActionExecutor(this.registry)
    this.behavior = new BehaviorController(settings.behavior)
    this.facing = settings.facing
    this.visible = settings.visible
    this.home = { ...spawn }
  }

  get position(): Vec2 {
    return { x: this.body.x, y: this.body.y }
  }

  get isDragging(): boolean {
    return this.userDragging
  }

  get currentGoal(): Vec2 | null {
    return this.goal ? { ...this.goal } : null
  }

  get plannedTilePath(): TileCell[] {
    return this.tilePath ? this.tilePath.slice(this.tileIndex) : []
  }

  setSpriteSize(width: number, height: number): void {
    this.settings.spriteWidth = Math.max(8, width)
    this.settings.spriteHeight = Math.max(8, height)
  }

  registerAction(definition: Parameters<ActionRegistry['register']>[0]): void {
    this.registry.register(definition)
  }

  clipFor(actionId: string): PetClip | undefined {
    const direct = this.settings.actions[actionId]
    if (direct) return direct
    const action = this.registry.get(actionId)
    const fallback = action?.fallback
    return fallback ? this.settings.actions[fallback] : undefined
  }

  /**
   * 有等待用户处理的审批/提问：停止自主行为与寻路，原地待机。
   *
   * user:"存在这些的时候桌宠不要动，保持待机"+"偶尔动一下就行了，
   * 为什么我感觉他永远都处在探索状态"+
   * (卡片存在期间不允许自主选靶/沿旧路径继续走；清空目标与路标，切到疑问动作。
   *  用户抓取仍然优先，松手后继续保持待机。)
   */
  setAttentionHold(hold: boolean): void {
    if (this.attentionHold === hold) return
    this.attentionHold = hold
    if (hold) {
      this.goal = null
      this.goalIsUser = false
      this.tilePath = null
      this.steerGoal = null
      this.dropIntent = false
      this.behavior.clearTarget('等待用户处理审批/提问')
      this.executor.request('question', { interrupt: true })
    } else {
      this.executor.request('idle', { interrupt: true })
    }
  }

  /** 用户开始抓取：立即交出控制权，保留当前速度。 */
  startDrag(point: Vec2): void {    this.userDragging = true
    // user:"碰撞箱不对，比实际偏高"+
    // (抓取以"鼠标到脚底"的偏移为锚：在角色哪个位置按下，就抓着那个位置走，
    //  不能把脚底直接弹到光标上——否则一抓起角色就整体上跳一个身高。)
    this.dragOffset = { x: point.x - this.body.x, y: point.y - this.body.y }
    this.dragTarget = { x: this.body.x, y: this.body.y }
    this.goal = null
    this.goalIsUser = false
    this.tilePath = null
    this.executor.force('interact')
    this.behavior.clearTarget('用户抓起')
  }

  updateDrag(point: Vec2): void {
    if (!this.userDragging) return
    this.dragTarget = { x: point.x - this.dragOffset.x, y: point.y - this.dragOffset.y }
  }

  /** 释放：继承实际速度自然坠落，不清零也不无限加速。 */
  endDrag(): void {
    this.userDragging = false
    this.dragTarget = null
    this.executor.releaseForce()
    // 给一个"被甩出去"的动作，物理继续用当前速度。
    this.executor.request(this.body.grounded ? 'idle' : 'fall')
  }

  /** 点击 Hitbox：直接执行动作，不弹菜单。 */
  clickAt(localX: number, localY: number): PetHitbox | null {
    const rect = this.visibleRect()
    const hitbox = hitTest(this.settings.hitboxes, localX, localY, rect.width, rect.height, this.facing)
    if (!hitbox) return null
    this.executor.force(hitbox.action)
    this.spriteElapsed = 0
    return hitbox
  }

  doubleClickAt(localX: number, localY: number): PetHitbox | null {
    const rect = this.visibleRect()
    const hitbox = hitTest(this.settings.hitboxes, localX, localY, rect.width, rect.height, this.facing)
    if (!hitbox) return null
    this.executor.force(hitbox.doubleAction || hitbox.action)
    this.spriteElapsed = 0
    return hitbox
  }

  /**
   * 交互 Hitbox 的世界矩形（与绘制、穿透上报同源）。
   *
   * user:"碰撞箱不对，比实际偏高"+
   * (角色没有启用任何 Hitbox 时退回整个精灵框，至少保证能点到、能拖动；
   *  有 Hitbox 时点击域严格等于画出来的粉色框。)
   */
  interactionRects(): Array<{ x: number; y: number; width: number; height: number }> {
    const rect = this.visibleRect()
    const enabled = this.settings.hitboxes.filter(hitbox => hitbox.enabled)
    if (enabled.length === 0) return [rect]
    return enabled.map(hitbox => hitboxWorldRect(hitbox, rect, this.facing))
  }

  /**
   * 点是否落在某个交互 Hitbox 上；命中时一并给出相对精灵框的本地坐标。
   * 物理碰撞体（AABB）不参与这里——它只负责地形。
   */
  hitTestPoint(point: Vec2): { hitbox: PetHitbox; localX: number; localY: number } | null {
    const rect = this.visibleRect()
    const localX = point.x - rect.x
    const localY = point.y - rect.y
    const hitbox = hitTest(this.settings.hitboxes, localX, localY, rect.width, rect.height, this.facing)
    return hitbox ? { hitbox, localX, localY } : null
  }

  /** 用户点击地图设目标：瓦片寻路并执行。 */
  setDestination(point: Vec2, context: { tiles: TileGrid; now: number }): 'ok' | 'unreachable' {
    this.goal = { ...point }
    this.goalIsUser = true
    return this.computeTilePath(context)
  }

  clearGoal(): void {
    this.goal = null
    this.goalIsUser = false
    this.tilePath = null
    this.steerGoal = null
    this.executor.request('idle', { interrupt: true })
  }

  /**
   * 瓦片寻路：从脚下到目标点。失败即放弃（泰拉瑞亚语义：寻路不到就不到）。
   */
  private computeTilePath(context: { tiles: TileGrid; now: number }): 'ok' | 'unreachable' {
    // 挂在檐下时，身体所在格（脚下那一行）是空的；起点要取"头贴板下沿的那一格"，
    // 否则 startCell 会一路向下找到地板，路径从地板开始算，执行对不上。
    const startY = this.body.hung ? this.body.y - this.body.height + 1 : this.body.y - 1
    const cells = context.tiles.findPath(this.body.x, startY, this.goal!.x, this.goal!.y - 1)
    if (!cells || cells.length === 0) {
      this.tilePath = null
      this.lastPlan = 'unreachable'
      if (this.goal) {
        const wasBehavior = !this.goalIsUser
        this.goal = null
        this.goalIsUser = false
        if (wasBehavior) this.behavior.clearTarget('目标不可达')
      }
      return 'unreachable'
    }
    this.lastPlan = 'ok'
    this.tilePath = cells
    // 起点格就是脚下：直接从下一个路标开始跟随。
    this.tileIndex = cells.length > 1 ? 1 : 0
    return 'ok'
  }

  /**
   * 推进一个渲染帧：内部按固定步长积分，低/高帧率下同种动作表现一致。
   */
  tick(context: PetTickContext): void {
    this.lastNow = context.now
    if (!this.visible) return
    if (context.dragging !== this.userDragging) this.userDragging = context.dragging

    let remaining = clamp(context.dtMs, 0, 100) / 1000
    let guard = 0
    while (remaining > 0 && guard < 40) {
      const dt = Math.min(PHYSICS_STEP, remaining)
      this.stepOnce(context, dt)
      remaining -= dt
      guard += 1
    }

    // 精灵帧推进与物理阶段无关，但播放时间由执行器记录的动作开始时间驱动。
    this.spriteElapsed += context.dtMs
  }

  private stepOnce(context: PetTickContext, dt: number): void {
    // 0) 有待处理的审批/提问：不选靶、不沿旧路径走，原地待机做疑问动作。
    if (this.attentionHold && !this.userDragging) {
      this.goal = null
      this.tilePath = null
      this.steerGoal = null
      this.dropIntent = false
      const current = this.executor.currentId
      // 用户主动触发的动作（互动/跳舞）先播完；其余状态回到疑问姿态。
      if (current !== 'interact' && current !== 'interact_head' && current !== 'dance') {
        this.executor.request('question', {
          interrupt: current !== null && current !== 'idle' && current !== 'rest' && current !== 'question',
        })
      }
    }
    // 1) 决策：行为只在没有用户目标、也没有待处理请求时接管。
    if (!this.userDragging && !this.attentionHold && !this.goal) {
      const decision = this.behavior.decide({
        now: context.now,
        position: this.position,
        mouse: context.mouse,
        tiles: context.tiles,
        home: this.home,
        busy: this.userDragging,
        halfWidth: this.body.width / 2,
      })
      if (decision.intent === 'wander' && decision.target) {
        this.goal = { ...decision.target }
        this.goalIsUser = false
        this.computeTilePath(context)
      } else if (decision.intent === 'rest') {
        if (!this.tilePath) this.executor.request('rest')
      }
    }

    // 2) 瓦片路径跟随：把下一个路标翻译成走/跳/落/爬/挂。
    this.followTiles(context, dt)

    // 3) Action → 物理意图。
    const actionGoal = this.steerGoal ?? this.goal
    const actionContext: ActionContext = {
      body: this.body,
      goal: actionGoal,
      facing: this.facing,
      now: context.now,
      elapsed: this.executor.elapsed,
      config: this.physics,
      ladderContact: context.tiles.bodyTouchesLadder(this.body.x, this.body.y),
    }
    if (!this.userDragging && !this.tilePath && this.goal) {
      // 无路径但有目标：直接走向目标（泰拉瑞亚 NPC 的兜底移动）。
      const dx = this.goal.x - this.body.x
      if (distance(this.position, this.goal) < TILE_SIZE * 0.8) {
        this.arrive(context.now)
      } else if (Math.abs(dx) > 6) {
        this.executor.request('walk')
      } else {
        this.executor.request('idle')
      }
    }
    const resolved = this.executor.update(actionContext)
    const intent = this.userDragging
      ? { dragTarget: this.dragTarget, ghost: true }
      : { ...(resolved?.intent || {}) }
    if (!this.userDragging && this.dropIntent && this.body.grounded) {
      // user:"平台可上也可下"+(站在单向板上、下一个路标在下方：提交下落穿过。)
      intent.dropThrough = true
    }
    if (intent.faceGoal && actionGoal) {
      const dx = actionGoal.x - this.body.x
      if (Math.abs(dx) > 4) this.facing = dx > 0 ? 1 : -1
    } else if (Math.abs(this.body.vx) > 20) {
      this.facing = this.body.vx > 0 ? 1 : -1
    }

    // 4) 物理（瓦片 AABB）。
    const events = stepBody(this.body, intent, this.physics, context.tiles, dt)
    this.lastEvents = events
    if (events.landed) {
      this.spriteElapsed = 0
      // 落地后重新寻路：地形可能已变化，绝不用空中折线继续跑。
      if (this.goal) this.computeTilePath(context)
    }
    if (events.jumped || events.hung) this.spriteElapsed = 0

    // 5) 卡住看门狗（泰拉瑞亚 NPC 语义：路走不通就重新寻路）。
    if (this.tilePath && this.goal && !this.userDragging && this.body.grounded && !this.body.climbing && !this.body.hung) {
      // 用"当前路标"而不是 steerGoal 判断：下行路标会把瞄准高度设成脚下，
      // 只看 steerGoal 会漏掉"水平对齐但高度差一大截"的卡死。
      const waypointCell = this.tilePath[this.tileIndex]
      const waypoint = waypointCell
        ? this.waypointFor(context.tiles, waypointCell, this.cellIsHang(context.tiles, waypointCell))
        : null
      const wantsToMove = waypoint !== null
        && (Math.abs(waypoint.x - this.body.x) > 4 || Math.abs(waypoint.y - this.body.y) > 8)
      const blocked = wantsToMove && Math.abs(this.body.vx) < 10
      this.stuckForMs = blocked ? this.stuckForMs + dt * 1000 : 0
      if (this.stuckForMs > 700 && context.now - this.lastStuckReplanAt > 1000) {
        this.stuckForMs = 0
        this.lastStuckReplanAt = context.now
        this.computeTilePath(context)
      }
    } else {
      this.stuckForMs = 0
    }
  }

  private steerGoal: Vec2 | null = null

  /** 当前路标的世界坐标：站瓦=顶面中心；檐下=头贴板底的脚位；绳梯=瓦中心。 */
  private waypointFor(tiles: TileGrid, cell: TileCell, hang: boolean): Vec2 {
    if (hang) {
      // 檐下：头顶贴上方单向板的底沿（板底 = 本行瓦的上沿），脚 = 板底 + 身高。
      return { x: tiles.bounds.x + (cell.col + 0.5) * TILE_SIZE, y: cell.row * TILE_SIZE + tiles.bounds.y + this.body.height }
    }
    return tiles.standPoint(cell.col, cell.row)
  }

  /** 当前路标是否"檐下"：头顶是单向板的空瓦。 */
  private cellIsHang(tiles: TileGrid, cell: TileCell): boolean {
    return tiles.isHangable(cell.col, cell.row)
  }

  private followTiles(context: PetTickContext, _dt: number): void {
    const tiles = context.tiles
    if (!this.tilePath) {
      this.steerGoal = null
      this.dropIntent = false
      return
    }
    // 连续路标推进：吃掉一个路标后立刻处理下一个，避免出现"这一帧没有动作
    // 请求"的空档——空档里执行器会按攀爬动作的完成条件收尾，把攀爬意图清掉，
    // 宠物就在半空脱手掉回楼下。
    for (let guard = 0; guard < 8; guard += 1) {
      if (this.tileIndex >= this.tilePath.length) {
        const arrived = this.goal && distance(this.position, this.goal) < TILE_SIZE * 0.8
        if (arrived) {
          this.arrive(context.now)
        } else {
          this.tilePath = null
          this.steerGoal = null
          this.dropIntent = false
        }
        return
      }
      if (!this.body.grounded && !this.body.climbing && !this.body.hung) {
        // 空中（跳跃/坠落中）：意图已定，等物理落地。
        return
      }
      const cell = this.tilePath[this.tileIndex]
      const isLast = this.tileIndex === this.tilePath.length - 1
      const hang = this.cellIsHang(tiles, cell)
      const wp = this.waypointFor(tiles, cell, hang)
      // 屏幕顶边的梯子格：脚最小只能到"屏幕顶 + 身高"（物理钳制），
      // 路标高度也钳到这条线，否则永远差一截、挂在梯顶不上不下。
      if (tiles.isLadder(cell.col, cell.row)) {
        const minY = tiles.bounds.y + this.body.height
        const maxY = tiles.bounds.y + tiles.bounds.height
        wp.y = Math.max(minY, Math.min(maxY, wp.y))
      }
      const dx = wp.x - this.body.x
      const dy = wp.y - this.body.y
      // user:"L1墙可沿边缘攀爬，就像梯子"+
      // (屏幕边缘的绳梯在墙里：角色中心被边界钳住对不齐梯子中线，
      //  只要身体贴到梯瓦就算抓附，路标判定也不再要求水平对齐。)
      const onLadderNow = tiles.bodyTouchesLadder(this.body.x, this.body.y)
      const reachX = clamp(wp.x, tiles.bounds.x + this.body.width / 2, tiles.bounds.x + tiles.bounds.width - this.body.width / 2)
      const fromCell = this.tilePath[Math.max(0, this.tileIndex - 1)]!
      const fromLadder = tiles.isLadder(fromCell.col, fromCell.row)
      // 路标判定要贴近真实落点：竖向容差过大会让宠物在"还差半格才爬到板顶"时
      // 就切到下一个路标，结果横向对齐把攀爬意图清掉、掉回楼下。
      // 绳梯上（或刚从绳梯上来）不要求水平对齐：边缘绳梯的中心被边界钳住。
      // 站瓦（板顶/地面）的竖向判定：脚必须已经到瓦面或更高，不能还在板面
      // 以下就"算到达"——否则会在板下 6px 切走，单向板接不住直接掉下去。
      const standSurface = tiles.isStandable(cell.col, cell.row) && !tiles.isLadder(cell.col, cell.row)
      const verticalOk = Math.abs(dy) < TILE_SIZE * 0.45 && (!standSurface || dy >= -0.005)
      const near = Math.abs(dx) < TILE_SIZE * 0.45 && verticalOk
        || (onLadderNow && (tiles.isLadder(cell.col, cell.row) || fromLadder) && verticalOk)

      // 绳梯顶端接站瓦：必须先在梯上把脚爬到站瓦高度（板顶/瓦顶），
      // 再判定到达或横移。提前 6px 切走会让身体停在板面以下，单向板接不住。
      if (fromLadder && (this.body.climbing || onLadderNow) && this.body.y > wp.y + 0.005) {
        this.executor.request('climb')
        this.steerGoal = { x: reachX, y: wp.y }
        this.dropIntent = false
        return
      }

      if (near) {
        if (isLast) {
          this.arrive(context.now)
          this.tilePath = null
          return
        }
        this.tileIndex += 1
        continue
      }

      // 檐下路标：走到悬挂点，头贴平台下沿时抓挂；已挂上就沿檐滑行。
      if (hang) {
        this.dropIntent = false
        this.executor.request('hang')
        this.steerGoal = { x: reachX, y: this.body.hung ? wp.y : this.body.y }
        return
      }

      // 绳梯路标：身体在梯上 → 攀爬上下；不在梯上 → 走向梯列。
      if (tiles.isLadder(cell.col, cell.row)) {
        if (this.body.climbing || onLadderNow) {
          this.executor.request('climb')
          this.steerGoal = { x: reachX, y: wp.y }
          return
        }
        this.executor.request(Math.abs(reachX - this.body.x) > 6 ? 'walk' : 'idle')
        this.steerGoal = { x: reachX, y: this.body.y }
        return
      }

      // 上行路标 = 跳跃边（泰拉瑞亚 NPC：遇到高台就跳）。
      if (dy < -TILE_SIZE * 0.5) {
        if (fromLadder) {
          // user:"竖边就像泰拉瑞亚里的绳子一样"+
          // (绳梯顶端接窗口顶平台：还没爬到板顶高度时继续爬，别横向对齐把攀爬
          //  意图清掉——半空脱手会掉回楼下。屏幕边缘的梯子用钳到边界内的 x。)
          this.executor.request('climb')
          this.steerGoal = { x: reachX, y: wp.y }
          this.dropIntent = false
          return
        }
        // user:"包括寻路，边，判定框全部都与泰拉瑞亚一致"+
        // (瓦片路标里"更高的站瓦"就是跳跃边：直接带着水平速度起跳，空中朝
        //  路标修正。先横移对齐再起跳会在窄平台边缘走出去掉下去——A* 认为
        //  能跳过去、执行却走着掉下去，两边语义不一致。)
        this.executor.request('jump')
        this.steerGoal = wp
        this.dropIntent = false
        return
      }

      // 下行路标：走向目标列；站在单向板上时提交下落穿过。
      if (dy > TILE_SIZE * 0.5) {
        if (this.body.hung) {
          // 挂在檐下要去更低处：必须保持悬挂动作并把瞄准点放到脚下，
          // 让悬挂动作提交 release；换成 walk/idle 只会沿檐滑动、永远不松手。
          this.executor.request('hang')
          this.steerGoal = {
            x: this.body.x + (Math.sign(cell.col - fromCell.col) || Math.sign(dx)) * TILE_SIZE * 2,
            y: this.body.y + this.body.height,
          }
          this.dropIntent = false
          return
        }
        const dropDir = Math.sign(cell.col - fromCell.col) || Math.sign(dx)
        if (dropDir !== 0) {
          // user:"包括寻路，边，判定框全部都与泰拉瑞亚一致"+
          // (路标在下方：朝落差方向持续迈步，直到真的走出支撑范围掉落。
          //  不能按 |dx| 来回切"走向路标/走落差"——站在窄墙顶上会左右抖动
          //  永远走不出去；以前 48px 瓦片时墙顶宽一格的抖动幅度刚好能掉下去，
          //  细瓦片下就卡死了。悬在檐下时把目标放到脚下，触发主动松手。)
          this.executor.request('walk')
          this.steerGoal = {
            x: this.body.x + dropDir * TILE_SIZE * 2,
            y: this.body.hung ? this.body.y + this.body.height : this.body.y,
          }
        } else {
          // 正下方同一列：单向板上提交下落，实心顶面原地等物理滑落。
          this.executor.request('idle')
          this.steerGoal = { x: wp.x, y: this.body.y }
        }
        const footCell = tiles.worldToCell(this.body.x, this.body.y + 2)
        this.dropIntent = tiles.typeAt(footCell.col, footCell.row) === 2
        return
      }

      // 平层：直接走向路标。
      this.dropIntent = false
      this.executor.request(Math.abs(dx) > 6 ? 'walk' : 'idle')
      this.steerGoal = wp
      return
    }
  }

  /** 到达当前目标：清目标并进入行为的停留节奏。 */
  private arrive(now: number): void {
    const wasBehavior = !this.goalIsUser
    this.goal = null
    this.goalIsUser = false
    this.tilePath = null
    this.steerGoal = null
    this.dropIntent = false
    if (wasBehavior) this.behavior.onArrived(now)
    // user:"为什么它都已经停在那里，也没有其他寻路目标点，但它依旧处于 walk 状态？"+
    // (到达后必须真的切到 idle：walk 优先级更高，普通请求会被挡住。)
    this.executor.request('idle', { interrupt: true })
  }

  /**
   * 角色可见矩形（精灵框，脚底锚定）。
   * 点击命中、交互 Hitbox 与穿透上报都以它为准；物理碰撞用 renderRect()。
   */
  visibleRect(): { x: number; y: number; width: number; height: number } {
    return spriteRect(
      this.position,
      this.settings.spriteWidth,
      this.settings.spriteHeight,
      this.settings.scale,
    )
  }

  renderRect(): { x: number; y: number; width: number; height: number } {
    // 判定框 = 泰拉瑞亚式 AABB（瓦片尺寸），脚底锚定。
    return { x: this.body.x - this.body.width / 2, y: this.body.y - this.body.height, width: this.body.width, height: this.body.height }
  }

  renderState(): PetRenderState {
    const rect = this.visibleRect()
    const actionId = this.executor.currentId || 'idle'
    const clip = this.clipFor(actionId)
    const geometry = this.geometryFor(clip)
    const frame = clip ? frameAt(clip, this.spriteElapsed, geometry) : null
    return {
      id: this.id,
      name: this.name,
      rect,
      box: this.renderRect(),
      frame,
      facing: this.facing,
      actionId,
      visible: this.visible,
      dragging: this.userDragging,
      velocity: { x: this.body.vx, y: this.body.vy },
      phase: this.body.phase,
      hitboxes: this.settings.hitboxes,
      spriteWidth: this.settings.spriteWidth,
      spriteHeight: this.settings.spriteHeight,
      scale: this.settings.scale,
      elapsedMs: this.spriteElapsed,
      clip,
    }
  }

  private geometryFor(clip: PetClip | undefined): ClipGeometry {
    if (!clip) return { width: this.settings.spriteWidth, height: this.settings.spriteHeight }
    if (clip.type === 'spritesheet') return { width: clip.frameWidth, height: clip.frameHeight }
    return { width: this.settings.spriteWidth, height: this.settings.spriteHeight }
  }

  diagnostics(): PetDiagnostics {
    const action = this.executor.currentAction
    const missing = action && !this.settings.actions[action.id] ? action.id : null
    return {
      id: this.id,
      actionId: this.executor.currentId,
      actionLabel: action?.label || action?.id || '无',
      transition: this.executor.lastTransition
        ? `${this.executor.lastTransition.from || '∅'} → ${this.executor.lastTransition.to}（${this.executor.lastTransition.reason}）`
        : '—',
      grounded: this.body.grounded,
      hung: this.body.hung,
      climbing: this.body.climbing,
      velocity: { x: this.body.vx, y: this.body.vy },
      position: { x: this.body.x, y: this.body.y },
      pathNodes: this.tilePath ? this.tilePath.length : 0,
      pathIndex: this.tileIndex,
      goal: this.goal ? { ...this.goal } : null,
      behavior: this.behavior.lastDecision.reason,
      missingAnimation: missing,
    }
  }

  lastStepEvents(): StepEvents | null {
    return this.lastEvents
  }

  /** 调试/预览器：直接把身体放到某个位置（不参与运行时的正常路径）。 */
  teleport(point: Vec2): void {
    this.body.x = point.x
    this.body.y = point.y
    this.body.vx = 0
    this.body.vy = 0
    this.tilePath = null
  }

  setHome(point: Vec2): void {
    this.home = { ...point }
  }

  updateSettings(patch: Partial<PetInstanceSettings>): void {
    Object.assign(this.settings, patch)
    if (patch.scale !== undefined) this.settings.scale = patch.scale
    if (patch.visible !== undefined) this.visible = patch.visible
    if (patch.behavior) this.behavior.setConfig(patch.behavior)
  }

  /** 默认动作：用于"指定 Action 测试"与预览。 */
  playAction(actionId: string): string {
    const diagnostic = this.executor.force(actionId)
    this.spriteElapsed = 0
    return diagnostic.reason
  }

  get now(): number {
    return this.lastNow
  }
}

export function createDefaultSettings(id: string, name: string): PetInstanceSettings {
  return {
    id,
    name,
    scale: 1,
    facing: 1,
    radius: 26,
    physics: {},
    behavior: {},
    hitboxes: defaultHitboxes(),
    actions: {},
    spriteWidth: 128,
    spriteHeight: 160,
    visible: true,
  }
}
