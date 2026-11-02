/**
 * Action：完整、独立、可注册的动作。
 *
 * user:“Action 是完整独立动作……不强制把面部、身体、尾巴动画实时混合”+
 * (同一时刻只跑一个 Action；jump 与 jump_happy 是两套动作，不做表情通道叠加。
 *  Action 只提交物理意图，不写世界坐标。)
 */
import { clamp, type Vec2 } from './math.ts'
import type { MotionIntent, PhysicsConfig, BodyState } from './physics.ts'

export type ActionId = string

export interface ActionContext {
  /** 物理事实（只读视图）：判定框、速度、接触、攀爬/悬挂。 */
  body: BodyState
  /** 当前目标点（自主行为或寻路给的目标）。 */
  goal: Vec2 | null
  /** 朝向，1 右 -1 左。 */
  facing: 1 | -1
  now: number
  /** 本动作已运行多少毫秒。 */
  elapsed: number
  config: PhysicsConfig
  /** 身体是否贴着绳梯瓦（攀爬动作的运行条件：离开梯子就该让位给跳/走）。 */
  ladderContact: boolean
}

export interface ActionIntent extends MotionIntent {
  /** 是否希望朝向目标。 */
  faceGoal?: boolean
}

export interface ActionDefinition {
  id: ActionId
  /** 抢占优先级：越大越强势。 */
  priority: number
  loop: boolean
  durationMs?: number
  /** 允许条件；不满足时执行器会解释失败原因。 */
  canRun?: (context: ActionContext) => boolean
  /** 能否被同级或更低优先级打断（用户抓取永远高于自主行为）。 */
  interruptible: boolean
  /** 动画缺失时的回退动作 id。 */
  fallback?: ActionId
  /** 结束后回到的 action（缺省 idle）。 */
  next?: ActionId
  /** 每帧提交的物理意图。 */
  intent?: (context: ActionContext, memory: ActionMemory) => ActionIntent
  /** 自定义完成条件；跳跃类靠物理落地而不是动画时长。 */
  isComplete?: (context: ActionContext, memory: ActionMemory) => boolean
  /** 动画标签，交给资源适配器解析；缺失时用 fallback。 */
  animation?: string
  /** 给调试与 UI 的中文名。 */
  label?: string
}

export interface ActionMemory {
  startedAt: number
  firedJump: boolean
  data: Record<string, unknown>
}

export interface ActionTransition {
  from: ActionId | null
  to: ActionId
  reason: 'start' | 'finished' | 'priority' | 'interrupt' | 'forced' | 'unavailable'
}

export interface ActionDiagnostic {
  requestedId: ActionId
  accepted: boolean
  reason: string
  fallbackUsed?: ActionId
}

export class ActionRegistry {
  private actions = new Map<ActionId, ActionDefinition>()

  register(action: ActionDefinition): void {
    this.actions.set(action.id, action)
  }

  registerAll(actions: ActionDefinition[]): void {
    for (const action of actions) this.register(action)
  }

  get(id: ActionId): ActionDefinition | undefined {
    return this.actions.get(id)
  }

  has(id: ActionId): boolean {
    return this.actions.has(id)
  }

  ids(): ActionId[] {
    return [...this.actions.keys()].sort()
  }

  /** 回退链：id → fallback → ... → idle，绝不返回不存在的动作。 */
  resolveWithFallback(id: ActionId): { action: ActionDefinition; usedFallback: boolean } | null {
    const seen = new Set<ActionId>()
    let current = id
    let usedFallback = false
    while (current && !seen.has(current)) {
      seen.add(current)
      const found = this.actions.get(current)
      if (found) return { action: found, usedFallback }
      current = this.actions.get(current)?.fallback || ''
      usedFallback = true
      if (!current) break
    }
    const idle = this.actions.get('idle')
    return idle ? { action: idle, usedFallback: true } : null
  }
}

/**
 * 内置基础动作。缺动画时仍然能运动、碰撞、寻路 —— 这些动作本身不依赖资源。
 */
export function buildDefaultActions(): ActionDefinition[] {
  return [
    {
      id: 'idle',
      priority: 0,
      loop: true,
      interruptible: true,
      animation: 'idle',
      label: '待机',
      intent: () => ({ vx: 0, faceGoal: false }),
    },
    {
      id: 'walk',
      priority: 10,
      loop: true,
      interruptible: true,
      fallback: 'idle',
      animation: 'walk',
      label: '行走',
      intent: (context) => {
        const goal = context.goal
        if (!goal) return { vx: 0 }
        const delta = goal.x - context.body.x
        const direction = Math.abs(delta) < 3 ? 0 : Math.sign(delta)
        return {
          vx: direction * context.config.walkSpeed,
          accel: context.config.accel,
          faceGoal: true,
        }
      },
    },
    {
      id: 'jump',
      priority: 40,
      loop: false,
      interruptible: false,
      fallback: 'idle',
      next: 'idle',
      animation: 'jump',
      label: '跳跃',
      intent: (context, memory) => {
        const jump = !memory.firedJump && context.body.grounded
        if (jump) memory.firedJump = true
        const goal = context.goal
        const desired = goal
          ? clamp(context.config.walkSpeed * Math.sign(goal.x - context.body.x), -context.config.walkSpeed, context.config.walkSpeed)
          : context.body.vx
        // user:"包括寻路，边，判定框全部都与泰拉瑞亚一致"+
        // (泰拉瑞亚 NPC 起跳后仍朝目标施力：被墙挡住时只有带着水平速度跳，
        //  身体升过墙顶后才能横移翻越。空中只给弱操控，由物理的 airControl 限制。)
        return {
          vx: desired,
          jump,
          faceGoal: true,
        }
      },
      isComplete: (context, memory) => memory.firedJump && context.body.grounded,
    },
    {
      // 和 jump 是两套完整动作，不共享表情通道。
      id: 'jump_happy',
      priority: 45,
      loop: false,
      interruptible: false,
      fallback: 'jump',
      next: 'idle',
      animation: 'jump_happy',
      label: '开心跳',
      intent: (context, memory) => {
        const jump = !memory.firedJump && context.body.grounded
        if (jump) memory.firedJump = true
        return { vx: undefined, jump, faceGoal: false }
      },
      isComplete: (context, memory) => memory.firedJump && context.body.grounded,
    },
    {
      id: 'fall',
      priority: 30,
      loop: true,
      interruptible: false,
      fallback: 'idle',
      animation: 'fall',
      label: '下坠',
      canRun: (context) => !context.body.grounded && !context.body.hung && !context.body.climbing,
      intent: () => ({ faceGoal: false }),
      isComplete: (context) => context.body.grounded || context.body.hung,
    },    {
      id: 'land',
      priority: 35,
      loop: false,
      durationMs: 220,
      interruptible: true,
      fallback: 'idle',
      next: 'idle',
      animation: 'land',
      label: '落地',
      intent: () => ({ vx: 0 }),
    },
    {
      id: 'climb',
      priority: 50,
      loop: true,
      interruptible: true,
      fallback: 'idle',
      animation: 'climb',
      label: '攀爬',
      // 不在梯子上时攀爬动作不能继续占着执行器（否则会挡住跳跃/行走请求，
      // 角色站在平台上一动不动）。
      canRun: (context) => context.body.climbing || context.ladderContact,
      // user:"竖边就像泰拉瑞亚里的绳子一样……它不是必须爬，但是它可以爬"+
      // (绳梯攀爬：意图始终可提交，物理只在身体与绳梯重叠时抓附；
      //  靠近路标即完成，交给下一段移动。)
      intent: (context) => {
        const goal = context.goal
        if (!goal) return { climb: 0 }
        const dy = goal.y - context.body.y
        const dx = goal.x - context.body.x
        return {
          climb: dy < -0.002 ? -1 : dy > 0.002 ? 1 : 0,
          vx: clamp(dx * 4, -context.config.walkSpeed, context.config.walkSpeed),
        }
      },
      isComplete: (context) => context.goal !== null
        && Math.abs(context.goal.x - context.body.x) <= 12
        && Math.abs(context.goal.y - context.body.y) <= 12,
    },
    {
      id: 'hang',
      priority: 55,
      loop: true,
      interruptible: false,
      fallback: 'idle',
      animation: 'hang',
      label: '悬挂',
      // user:"平台可上也可下，也可站也可挂"+(挂在檐下也是合法状态：
      //  沿檐滑向目标；目标落到脚下超过半个身位即松手。)
      intent: (context) => {
        const goal = context.goal
        // 到达悬挂目标后原地挂着不动（"可挂"是状态，不是到了就松手）。
        if (!goal) return { hang: true, vx: 0 }
        if (goal.y > context.body.y + context.config.hitboxHeight * 0.5) {
          return { hang: true, release: true }
        }
        const direction = Math.sign(goal.x - context.body.x)
        return { hang: true, vx: direction * context.config.hangSpeed }
      },
      isComplete: (context) => !context.body.hung,
    },
    {
      id: 'dance',
      priority: 60,
      loop: false,
      durationMs: 2600,
      interruptible: true,
      fallback: 'idle',
      next: 'idle',
      animation: 'dance',
      label: '跳舞',
      intent: () => ({ vx: 0 }),
    },
    {
      id: 'interact',
      priority: 70,
      loop: false,
      durationMs: 700,
      interruptible: true,
      fallback: 'idle',
      next: 'idle',
      animation: 'interact',
      label: '互动',
      intent: () => ({ vx: 0 }),
    },
    {
      id: 'rest',
      priority: 5,
      loop: true,
      interruptible: true,
      fallback: 'idle',
      animation: 'rest',
      label: '休息',
      intent: () => ({ vx: 0 }),
    },
    {
      // user:"或者你加一个疑问动作"+
      // (有待回答的审批/提问时，桌宠停下来做一个疑问姿态：手举起来、歪头，
      //  比站桩更容易被注意到；它只提交"原地不动"的意图，不参与寻路。)
      id: 'question',
      priority: 8,
      loop: true,
      interruptible: true,
      fallback: 'idle',
      animation: 'question',
      label: '疑问',
      intent: () => ({ vx: 0, faceGoal: false }),
    },
    {
      id: 'interact_head',
      priority: 70,
      loop: false,
      durationMs: 900,
      interruptible: true,
      fallback: 'interact',
      next: 'idle',
      animation: 'interact_head',
      label: '摸头',
      intent: () => ({ vx: 0 }),
    },
  ]
}

/**
 * 动作执行器。
 *
 * 调度顺序：候选意图 → 执行许可 → 优先级比较 → 选中 Action →
 * 物理执行 → 动画响应物理阶段。同优先级保留当前动作，避免反复抖动。
 */
export class ActionExecutor {
  private current: ActionDefinition | null = null
  private memory: ActionMemory = { startedAt: 0, firedJump: false, data: {} }
  private forced: ActionId | null = null
  private pendingRequest: ActionId | null = null
  /** 本次请求允许无视优先级（移动控制器说"停下"时必须真的停下）。 */
  private pendingInterrupt = false
  /** 最近一次切换原因，供调试叠层显示。 */
  lastTransition: ActionTransition | null = null
  lastDiagnostic: ActionDiagnostic | null = null

  constructor(public readonly registry: ActionRegistry) {}

  get currentId(): ActionId | null {
    return this.current?.id ?? null
  }

  get currentAction(): ActionDefinition | null {
    return this.current
  }

  get elapsed(): number {
    return this.memory.startedAt === 0 ? 0 : Date.now() - this.memory.startedAt
  }

  /** 用户直接操作（抓取、点击、右键）拥有最高控制权。 */
  force(id: ActionId): ActionDiagnostic {
    const resolved = this.registry.resolveWithFallback(id)
    if (!resolved) {
      return this.diagnose(id, false, '没有任何可用动作')
    }
    this.forced = id
    this.pendingRequest = id
    return this.diagnose(id, true, resolved.usedFallback ? `动画缺失，回退到 ${resolved.action.id}` : '用户操作', resolved.usedFallback ? resolved.action.id : undefined)
  }

  /**
   * 自主行为提出候选动作。
   * interrupt=true：无视优先级直接切换（到达/清空目标时的 idle 用——
   *  否则 walk 优先级更高，会一直占着执行器，角色停住了还在播走路）。
   */
  request(id: ActionId, options?: { interrupt?: boolean }): ActionDiagnostic {
    const resolved = this.registry.resolveWithFallback(id)
    if (!resolved) return this.diagnose(id, false, '没有任何可用动作')
    this.pendingRequest = id
    this.pendingInterrupt = !!options?.interrupt
    return this.diagnose(id, true, resolved.usedFallback ? `回退到 ${resolved.action.id}` : '候选', resolved.usedFallback ? resolved.action.id : undefined)
  }

  releaseForce(): void {
    this.forced = null
  }

  private diagnose(id: ActionId, accepted: boolean, reason: string, fallbackUsed?: ActionId): ActionDiagnostic {
    const diagnostic: ActionDiagnostic = { requestedId: id, accepted, reason, fallbackUsed }
    this.lastDiagnostic = diagnostic
    return diagnostic
  }

  /**
   * 每帧调用：解析候选、应用优先级、返回本帧物理意图。
   * 返回 null 表示没有可执行动作（此时物理仍然继续跑）。
   */
  update(context: ActionContext): { action: ActionDefinition; intent: ActionIntent } | null {
    const candidateId = this.pendingRequest
    if (candidateId) {
      this.pendingRequest = null
      const interrupt = this.pendingInterrupt
      this.pendingInterrupt = false
      const resolved = this.registry.resolveWithFallback(candidateId)
      const allowed = resolved && (resolved.action.canRun ? resolved.action.canRun(context) : true)
      if (interrupt && resolved && allowed) {
        if (resolved.action.id !== this.current?.id) this.apply(resolved.action, context, 'interrupt')
        else this.memory = { startedAt: context.now, firedJump: false, data: {} }
      } else {
        this.maybeSwitch(candidateId, context)
      }
    } else if (this.current) {
      const finished = this.isFinished(this.current, context)
      const stillAllowed = this.current.canRun ? this.current.canRun(context) : true
      if (finished || !stillAllowed) {
        const nextId = this.current.next || 'idle'
        this.switchTo(nextId, context, 'finished')
      }
    } else {
      this.switchTo('idle', context, 'start')
    }
    if (!this.current) return null
    const intent = this.current.intent ? this.current.intent(context, this.memory) : {}
    return { action: this.current, intent }
  }

  private maybeSwitch(candidateId: ActionId, context: ActionContext): void {
    const resolved = this.registry.resolveWithFallback(candidateId)
    if (!resolved) return
    const candidate = resolved.action
    const current = this.current
    if (!current) {
      this.apply(candidate, context, 'start')
      return
    }
    if (candidate.id === current.id) {
      // 同一个动作被持续请求时也要检查完成：跳跃的 memory.firedJump 会一直
      // 停在 true，不重置就永远不再起跳（角色贴着地面干跳/发呆）。
      if (this.isFinished(current, context)) this.apply(candidate, context, 'finished')
      return
    }
    if (this.forced && resolved.usedFallback) {
      // 强制动作自身缺资源时不要用回退顶掉更强的强制动作。
      if (current.priority >= candidate.priority) return
    }
    const allowed = candidate.canRun ? candidate.canRun(context) : true
    if (!allowed) {
      this.diagnose(candidateId, false, `${candidate.label || candidate.id} 当前条件不满足`)
      return
    }
    const currentFinished = this.isFinished(current, context)
    const currentAllowed = current.canRun ? current.canRun(context) : true
    const forcedSwitch = this.forced === candidate.id
    // 只有严格更高优先级、当前动作已完成、或当前动作条件失效才切换；
    // 同优先级一律保留当前动作（避免来回抖动）。
    if (forcedSwitch
      || candidate.priority > current.priority
      || currentFinished
      || !currentAllowed) {
      this.apply(candidate, context, forcedSwitch ? 'forced' : candidate.priority > current.priority ? 'priority' : 'finished')
      return
    }
    // 同优先级、当前不可被中断：保留当前动作，避免逐帧抖动。
  }

  private switchTo(id: ActionId, context: ActionContext, reason: ActionTransition['reason']): void {
    const resolved = this.registry.resolveWithFallback(id)
    if (!resolved) return
    this.apply(resolved.action, context, reason)
  }

  private apply(action: ActionDefinition, context: ActionContext, reason: ActionTransition['reason']): void {
    this.lastTransition = { from: this.current?.id ?? null, to: action.id, reason }
    this.current = action
    this.memory = { startedAt: context.now, firedJump: false, data: {} }
  }

  private isFinished(action: ActionDefinition, context: ActionContext): boolean {
    if (action.loop && !action.isComplete) return false
    if (action.isComplete && action.isComplete(context, this.memory)) return true
    if (action.durationMs !== undefined) {
      const elapsed = context.now - this.memory.startedAt
      return elapsed >= action.durationMs
    }
    return false
  }

  /** 调试/可视化：当前动作的物理意图快照。 */
  describe(): { id: ActionId | null; elapsedMs: number; forced: ActionId | null } {
    return {
      id: this.currentId,
      elapsedMs: this.memory.startedAt === 0 ? 0 : Date.now() - this.memory.startedAt,
      forced: this.forced,
    }
  }
}
