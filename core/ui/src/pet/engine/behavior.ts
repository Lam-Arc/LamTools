/**
 * 本地自主行为。
 *
 * user:“本地计时/事件驱动地选择休息、探索、移动、停留与互动；目的地软偏向
 * 鼠标附近，但不会始终追踪鼠标”+
 * (目标一旦选中，除非失效/用户操作/更高优先级任务，否则不反复改选；
 *  全程不请求模型。)
 */
import { clamp, distance, makeRandom, type Vec2 } from './math.ts'
import { TILE_SIZE, type TileGrid } from './tiles.ts'

export interface BehaviorConfig {
  enabled: boolean
  /** 探索强度 0..1：越高越愿意走远（偏好目标距离随它从 0 增长到活动半径）。 */
  activity: number
  /** 休息倾向 0..1。 */
  restChance: number
  /** 每次决策真正出门探索的概率 0..1；其余时间原地停留。 */
  wanderChance: number
  /** 鼠标附近的目标偏好权重 0..1（只影响挑目标，不进寻路成本）。 */
  mouseBias: number
  /** 活动半径（物理像素）。 */
  exploreRadius: number
  idleMinMs: number
  idleMaxMs: number
  restMinMs: number
  restMaxMs: number
}

// user:"偶尔动一下就行了，为什么我感觉他永远都处在探索状态"+
// (默认改成"大部分时间待着"：每次决策 45% 休息、剩下的只有 30% 真的出门，
//  停留窗口 8–20 秒；一次探索平均间隔约半分钟，而不是每 1–4 秒就换目标。)
export const DEFAULT_BEHAVIOR: BehaviorConfig = {
  enabled: true,
  activity: 0.45,
  restChance: 0.45,
  wanderChance: 0.3,
  mouseBias: 0.45,
  exploreRadius: 800,
  idleMinMs: 8000,
  idleMaxMs: 20000,
  restMinMs: 8000,
  restMaxMs: 24000,
}

export type BehaviorIntent = 'idle' | 'rest' | 'wander'

/** 到达判定半径（物理像素）：目标点在这个范围内即视为"已到"。 */
const ARRIVAL_RADIUS_PX = 24

/**
 * 鼠标偏置的最大跨楼层高差（物理像素，6 格）。
 *
 * user:"那我问你，这个桌宠它站在最下边，凭什么会认为它离最上边这么更近？"+"改"+
 * (鼠标只是"想让它待在哪一块桌面"的软偏好，不该变成爬楼指令：目标比脚下高
 *  超过这个高度时鼠标分线性衰减到 0，鼠标放在上方窗口里也不会把角色拉上去。)
 */
const MOUSE_BIAS_MAX_RISE = TILE_SIZE * 6

export interface BehaviorDecision {
  intent: BehaviorIntent
  target: Vec2 | null
  /** 命中的候选瓦片（可站/可挂），供调试。 */
  cell: { col: number; row: number } | null
  reason: string
}

export interface BehaviorInputs {
  now: number
  position: Vec2
  mouse: Vec2 | null
  tiles: TileGrid
  home: Vec2
  busy: boolean
  /** 判定框半宽（贴墙/贴边时的"脚下"判定用）。 */
  halfWidth: number
}

/**
 * 决策频率远低于物理频率：新目标只在"到点/超时/失效/用户操作"之后、且停留或
 * 重试空闲窗（idleMinMs..idleMaxMs、图不可用 1500ms）结束时才重新挑选；
 * 目标有效期间每帧只是原样保持，不重新打分。
 */
export class BehaviorController {
  config: BehaviorConfig
  private target: { point: Vec2; expiresAt: number } | null = null
  private nextDecisionAt = 0
  private resting = false
  private restUntil = 0
  private random = makeRandom(0x5eed)
  lastDecision: BehaviorDecision = { intent: 'idle', target: null, cell: null, reason: '未开始' }

  constructor(config: Partial<BehaviorConfig> = {}) {
    this.config = { ...DEFAULT_BEHAVIOR, ...config }
  }

  setConfig(patch: Partial<BehaviorConfig>): void {
    this.config = { ...this.config, ...patch }
  }

  get currentTarget(): Vec2 | null {
    return this.target?.point ?? null
  }

  /** 目标失效时由外部清空（例如地形变化、寻路失败）。 */
  clearTarget(reason: string): void {
    this.target = null
    this.lastDecision = { intent: 'idle', target: null, cell: null, reason }
  }

  /**
   * 返回本帧的行为意图。目标仍有效时返回同一个目标，
   * 只有到点、超时、失效或用户操作才重选。
   */
  decide(input: BehaviorInputs): BehaviorDecision {
    if (!this.config.enabled) return { intent: 'idle', target: null, cell: null, reason: '自主行为已关闭' }
    if (input.busy) return { intent: 'idle', target: null, cell: null, reason: '用户或高优先级任务控制中' }

    if (this.resting && input.now < this.restUntil) {
      return { intent: 'rest', target: null, cell: null, reason: '正在休息' }
    }
    if (this.resting) {
      this.resting = false
      this.nextDecisionAt = 0
    }

    if (this.target) {
      const done = distance(input.position, this.target.point) <= ARRIVAL_RADIUS_PX
      if (!done && input.now < this.target.expiresAt) {
        return { intent: 'wander', target: this.target.point, cell: null, reason: '保持已选目标' }
      }
      if (done) {
        // user:"本地计时/事件驱动地选择休息、探索、移动、停留与互动"+
        // (到点视同路径完成：清目标并进入随机停留空闲窗，与 onArrived 同一节奏，
        //  避免到达瞬间立刻改选下一个目标。)
        this.onArrived(input.now)
      } else {
        this.target = null
      }
    }

    if (input.now < this.nextDecisionAt) {
      return { intent: 'idle', target: null, cell: null, reason: '等待下一次决策' }
    }

    return this.pickNewTarget(input)
  }

  private pickNewTarget(input: BehaviorInputs): BehaviorDecision {
    const roll = this.random()
    if (roll < this.config.restChance) {
      this.resting = true
      const duration = this.config.restMinMs
        + this.random() * Math.max(1, this.config.restMaxMs - this.config.restMinMs)
      this.restUntil = input.now + duration
      this.nextDecisionAt = this.restUntil
      const decision: BehaviorDecision = { intent: 'rest', target: null, cell: null, reason: '休息倾向触发' }
      this.lastDecision = decision
      return decision
    }

    // user:"偶尔动一下就行了"+
    // (设计里的"停留"：没休息也不一定出门。掷骰决定继续待着，只是把下一次
    //  决策窗口往后推；这样角色不会永远在探索/走路的循环里。)
    if (this.random() > this.config.wanderChance) {
      const stay = this.config.idleMinMs
        + this.random() * Math.max(1, this.config.idleMaxMs - this.config.idleMinMs)
      this.nextDecisionAt = input.now + stay
      const decision: BehaviorDecision = { intent: 'idle', target: null, cell: null, reason: '停留' }
      this.lastDecision = decision
      return decision
    }

    // 目的地 = 可站立点。悬挂点不参与选靶（它是通行/手动目标，见 standPoints 注释）。
    const all = input.tiles.standPoints()
    if (all.length === 0) {
      this.nextDecisionAt = input.now + 1500
      return { intent: 'idle', target: null, cell: null, reason: '还没有可站立地形' }
    }

    // user:"莫名其妙走到角落，调试面板就显示目标不可达，但他一直在往左走"+
    // (可达性过滤：只在"从这里可达"的瓦片里挑目标——泰拉瑞亚语义：不可达的
    //  目标不会被选中。贴边时"脚下"判定按判定框半宽放宽，否则墙角原地走。)
    const nearRadius = Math.max(TILE_SIZE * 0.9, input.halfWidth * 1.2)
    // 选靶用"实际可走路程"而不是直线距离：爬天花板要一层层走上去，
    // 不能因为几何上只有 480px 就当成附近的目的地。
    const reachable = input.tiles.reachableDistances(input.position.x, input.position.y - 1)
    const selectable = (p: { x: number; y: number; col: number; row: number }): boolean => {
      if (distance(p, input.position) <= nearRadius) return false
      if (reachable === null) return true
      return reachable.has(input.tiles.index(p.col, p.row))
    }
    const candidates = all.filter(p => selectable(p) && distance(p, input.home) <= this.config.exploreRadius)
    const pool = candidates.length > 0 ? candidates : all.filter(selectable)
    if (pool.length === 0) {
      this.nextDecisionAt = input.now + 1500
      return { intent: 'idle', target: null, cell: null, reason: '没有可达的候选点' }
    }
    const scored = pool.map(point => {
      const travel = reachable?.get(input.tiles.index(point.col, point.row))
      // 有可达图时用瓦片路程（≈像素），没有时退化为直线距离。
      const fromHere = travel !== undefined ? travel * TILE_SIZE : distance(point, input.position)
      // user:"ACT-11 活跃度/范围/休息倾向可调并保存"（字段语义：探索强度越高越愿意走远）+
      // (偏好距离随活跃度从 0 增长到活动半径：activity=0 只在脚下附近挑，
      //  activity=1 愿意走满半径。)
      const preferred = this.config.exploreRadius * 0.9 * this.config.activity
      const distanceScore = 1 - clamp(Math.abs(fromHere - preferred) / (this.config.exploreRadius || 1), 0, 1)
      // 鼠标偏置只在"同一层附近"生效：高差越大衰减越快，超过 6 格直接为 0。
      const verticalGap = Math.abs(point.y - input.position.y)
      const verticalFactor = clamp(1 - verticalGap / MOUSE_BIAS_MAX_RISE, 0, 1)
      const mouseScore = input.mouse && this.config.mouseBias > 0
        ? (1 - clamp(distance(point, input.mouse) / (this.config.exploreRadius || 1), 0, 1)) * this.config.mouseBias * verticalFactor
        : 0
      const noise = this.random() * (1 - this.config.activity) * 0.5
      return { point, score: distanceScore + mouseScore + noise }
    })
    scored.sort((a, b) => b.score - a.score)
    const chosen = scored[0]!.point
    this.target = {
      point: { x: chosen.x, y: chosen.y },
      // 目标超时：卡太久就放弃，避免永远追逐一个到不了的点。
      expiresAt: input.now + 20000,
    }
    this.nextDecisionAt = input.now + this.config.idleMinMs
    const decision: BehaviorDecision = {
      intent: 'wander',
      target: this.target.point,
      cell: { col: chosen.col, row: chosen.row },
      reason: input.mouse && this.config.mouseBias > 0 ? '探索（偏好鼠标附近）' : '探索',
    }
    this.lastDecision = decision
    return decision
  }

  /** 完成后进入一段随机空闲，避免连续动作导致抖动。 */
  onArrived(now: number): void {
    this.target = null
    this.nextDecisionAt = now + this.config.idleMinMs
      + this.random() * Math.max(1, this.config.idleMaxMs - this.config.idleMinMs)
  }
}
