/**
 * 块E · 行为决策验收（瓦片世界版）。
 *
 * user:"所有的行为完全按照《泰拉瑞亚》去对齐"+
 * (候选点 = 瓦片世界的可站立点与檐下可挂点；可达性 = 瓦片可达集合——
 *  不可达目标不被选中；已选目标保持；到点停留；探索/休息/活跃度可调。)
 */
import { describe, expect, it } from 'vitest'
import { BehaviorController, DEFAULT_BEHAVIOR, type BehaviorInputs } from '@/pet/engine/behavior.ts'
import { parseConfigText, defaultConfig } from '@/pet/config.ts'
import type { TileGrid } from '@/pet/engine/tiles.ts'
import { TILE_SIZE } from '@/pet/engine/tiles.ts'
import { PetInstance, createDefaultSettings } from '@/pet/engine/pet.ts'
import { PetWorld } from '@/pet/engine/world.ts'

const SCREEN = { x: 0, y: 0, width: 1280, height: 800 }

/** 行为决策只读 standPoints/reachableTiles，手工构造最小瓦片世界。 */
function fakeTiles(points: Array<{ x: number; y: number }>): TileGrid {
  return {
    standPoints: () => points.map((p, i) => ({ ...p, col: i, row: 0 })),
    reachableTiles: () => null,
    reachableDistances: () => null,
    index: (col: number) => col,
  } as unknown as TileGrid
}

function inputs(patch: Partial<BehaviorInputs> & { tiles: TileGrid }): BehaviorInputs {
  return {
    now: 1000,
    position: { x: 0, y: 500 },
    mouse: null,
    home: { x: 0, y: 500 },
    busy: false,
    halfWidth: 30,
    ...patch,
  }
}

/** near/far 双点基准：距 pet/home 150 与 700（默认 exploreRadius=900 都覆盖）。 */
const NEAR_FAR_TILES = fakeTiles([
  { x: 150, y: 474 },
  { x: 700, y: 474 },
])

function steadyController(patch = {}): BehaviorController {
  // activity=1 时打分噪声为 0，决策完全可复现；restChance=0 排除休息分支，
  // wanderChance=1 排除"停留"分支。
  return new BehaviorController({ restChance: 0, wanderChance: 1, mouseBias: 0, activity: 1, ...patch })
}

describe('块E · 探索目标选取（ACT-08）', () => {
  it('图可用时自主选出探索目标，目标是瓦片候选点', () => {
    const controller = steadyController()
    const tiles = fakeTiles([
      { x: 200, y: 474 },
      { x: 500, y: 474 },
      { x: 800, y: 474 },
    ])
    const decision = controller.decide(inputs({ tiles, now: 1000 }))
    expect(decision.intent).toBe('wander')
    expect(decision.target).not.toBeNull()
    const matched = tiles.standPoints().some(p => p.x === decision.target!.x && p.y === decision.target!.y)
    expect(matched).toBe(true)
    expect(controller.currentTarget).toEqual(decision.target)
  })

  it('不选脚下已到达（≤24px）的点：目标必须是自己还没到的地方', () => {
    const controller = steadyController()
    const tiles = fakeTiles([
      { x: 0, y: 500 },
      { x: 300, y: 500 },
    ])
    const decision = controller.decide(inputs({ tiles }))
    expect(decision.target!.x).toBe(300)
  })

  it('唯一候选是脚下点时：不出目标，保持待机等待', () => {
    const controller = steadyController()
    const tiles = fakeTiles([{ x: 0, y: 500 }])
    const decision = controller.decide(inputs({ tiles }))
    expect(decision.intent).toBe('idle')
    expect(controller.currentTarget).toBeNull()
  })

  it('全程本地决策、无模型调用：只依赖 math/tiles 且不引 engine 其他模块', () => {
    const source: string = require('node:fs').readFileSync(require('node:path').resolve(process.cwd(), 'src/pet/engine/behavior.ts'), 'utf8')
    expect(source).not.toMatch(/fetch\s*\(/)
    expect(source).not.toMatch(/XMLHttpRequest|WebSocket/)
    const importLines = source.split('\n').filter(line => line.trim().startsWith('import '))
    for (const line of importLines) {
      expect(line).toMatch(/from '\.\/(math|tiles)\.ts'/)
    }
  })
})

describe('块E · 休息节奏（ACT-08）', () => {
  it('休息触发后保持到点，时长落在 [restMinMs, restMaxMs]', () => {
    const controller = steadyController({ restChance: 1, restMinMs: 3000, restMaxMs: 6000 })
    const tiles = NEAR_FAR_TILES
    const first = controller.decide(inputs({ tiles, now: 1000 }))
    expect(first.intent).toBe('rest')
    const during = controller.decide(inputs({ tiles, now: 3999 }))
    expect(during.intent).toBe('rest')
    expect(during.reason).toBe('正在休息')
    const after = controller.decide(inputs({ tiles, now: 7001 }))
    expect(after.reason).toBe('休息倾向触发')
  })

  it('用户或更高优先级任务期间立即让位（不输出 rest/wander）', () => {
    const controller = steadyController({ restChance: 1 })
    controller.decide(inputs({ tiles: NEAR_FAR_TILES, now: 1000 }))
    const busyWhileRest = controller.decide(inputs({ tiles: NEAR_FAR_TILES, now: 1016, busy: true }))
    expect(busyWhileRest.intent).toBe('idle')
    expect(busyWhileRest.reason).toContain('用户或高优先级')
  })
})

describe('块E · 鼠标附近只是软偏好（ACT-09）', () => {
  it('mouseBias 高时目标偏向鼠标附近（等距候选下由鼠标决定）', () => {
    const controller = steadyController({ mouseBias: 0.9 })
    const tiles = fakeTiles([
      { x: 405, y: 500 },
      { x: 0, y: 95 },
    ])
    const decision = controller.decide(inputs({ tiles, mouse: { x: 405, y: 500 } }))
    expect(decision.target!.x).toBe(405)
  })

  it('鼠标在上方也不会把角色往高处拉（高差超过 6 格鼠标分为 0）', () => {
    // user:"那我问你，这个桌宠它站在最下边，凭什么会认为它离最上边这么更近？"+"改"
    const tiles = fakeTiles([
      { x: 0, y: 20 }, // 正上方的天花板点：离鼠标最近
      { x: 300, y: 474 }, // 同层地面点
    ])
    const controller = steadyController({ mouseBias: 0.6, activity: 0.55 })
    const decision = controller.decide(inputs({
      tiles,
      position: { x: 0, y: 500 },
      home: { x: 0, y: 500 },
      mouse: { x: 0, y: 20 },
    }))
    expect(decision.target).toEqual({ x: 300, y: 474 })
  })

  it('目标选定后不追踪鼠标：鼠标移开仍保持原目标', () => {
    const controller = steadyController({ mouseBias: 0.9 })
    const tiles = NEAR_FAR_TILES
    const first = controller.decide(inputs({ tiles, mouse: { x: 700, y: 474 }, now: 1000 }))
    expect(first.intent).toBe('wander')
    const second = controller.decide(inputs({ tiles, mouse: { x: 150, y: 474 }, now: 1016 }))
    expect(second.intent).toBe('wander')
    expect(second.reason).toBe('保持已选目标')
    expect(second.target).toEqual(first.target)
  })
})

describe('块E · 已选目标保持（ACT-10）', () => {
  it('连续多帧（鼠标乱动）目标不变，不每帧改选', () => {
    const controller = steadyController()
    const tiles = NEAR_FAR_TILES
    const first = controller.decide(inputs({ tiles, now: 1000 }))
    expect(first.intent).toBe('wander')
    for (let frame = 1; frame <= 60; frame += 1) {
      const decision = controller.decide(inputs({
        tiles,
        now: 1000 + frame * 16,
        mouse: { x: (frame * 97) % 1280, y: (frame * 53) % 800 },
        position: { x: 0 + frame * 0.1, y: 500 },
      }))
      expect(decision.target).toEqual(first.target)
      expect(decision.reason).toBe('保持已选目标')
    }
  })

  it('到点（≤24px）后进入停留空闲窗，窗口过后才重选', () => {
    const controller = steadyController({ idleMinMs: 800, idleMaxMs: 800 })
    const tiles = NEAR_FAR_TILES
    const first = controller.decide(inputs({ tiles, now: 1000 }))
    expect(first.target).not.toBeNull()
    const arrived = controller.decide(inputs({ tiles, now: 5000, position: { ...first.target! } }))
    expect(arrived.intent).toBe('idle')
    expect(arrived.reason).toBe('等待下一次决策')
    expect(controller.currentTarget).toBeNull()
    const next = controller.decide(inputs({ tiles, now: 6000, position: { ...first.target! } }))
    expect(next.intent).toBe('wander')
  })

  it('目标超时（20s 未到达）后放弃并重选，新目标重新计时', () => {
    const controller = steadyController()
    const tiles = NEAR_FAR_TILES
    const first = controller.decide(inputs({ tiles, now: 1000 }))
    expect(first.intent).toBe('wander')
    const rePick = controller.decide(inputs({ tiles, now: 1000 + 20001 }))
    expect(rePick.intent).toBe('wander')
    expect(rePick.reason).not.toBe('保持已选目标')
    const held = controller.decide(inputs({ tiles, now: 1000 + 20017 }))
    expect(held.reason).toBe('保持已选目标')
    expect(held.target).toEqual(rePick.target)
  })

  it('clearTarget（用户操作）后旧目标作废', () => {
    const controller = steadyController()
    const tiles = NEAR_FAR_TILES
    const first = controller.decide(inputs({ tiles, now: 1000 }))
    expect(first.target).not.toBeNull()
    controller.clearTarget('用户抓起')
    expect(controller.currentTarget).toBeNull()
    const after = controller.decide(inputs({ tiles, now: 1016 }))
    expect(after.target).not.toEqual(first.target)
  })
})

describe('块E · 图不可用时的处理', () => {
  it('无候选点：不出错、不出目标、延迟重试', () => {
    const controller = steadyController()
    const empty = fakeTiles([])
    expect(() => controller.decide(inputs({ tiles: empty, now: 0 }))).not.toThrow()
    const first = controller.decide(inputs({ tiles: empty, now: 0 }))
    expect(first.intent).toBe('idle')
    expect(first.target).toBeNull()
  })
})

describe('块E · 活跃度/范围/休息倾向可调并保存（ACT-11）', () => {
  it('BehaviorConfig 全字段存在且 setConfig 可调', () => {
    expect(Object.keys(DEFAULT_BEHAVIOR).sort()).toEqual([
      'activity', 'enabled', 'exploreRadius', 'idleMaxMs', 'idleMinMs',
      'mouseBias', 'restChance', 'restMaxMs', 'restMinMs', 'wanderChance',
    ].sort())
    const controller = new BehaviorController()
    controller.setConfig({
      enabled: false, activity: 0.1, restChance: 0.9, mouseBias: 0.2,
      exploreRadius: 640, idleMinMs: 500, idleMaxMs: 2000, restMinMs: 1000, restMaxMs: 4000,
    })
    expect(controller.config).toMatchObject({
      enabled: false, activity: 0.1, restChance: 0.9, mouseBias: 0.2,
      exploreRadius: 640, idleMinMs: 500, idleMaxMs: 2000, restMinMs: 1000, restMaxMs: 4000,
    })
  })

  it('exploreRadius 活动半径门控候选：半径外的点不选', () => {
    const controller = steadyController({ exploreRadius: 200 })
    const decision = controller.decide(inputs({ tiles: NEAR_FAR_TILES }))
    expect(decision.target!.x).toBe(150)
  })

  it('activity 越高越愿意走远：高活跃度选远节点，低活跃度选近节点', () => {
    const far = steadyController({ activity: 1 })
    const near = steadyController({ activity: 0 })
    const farDecision = far.decide(inputs({ tiles: NEAR_FAR_TILES }))
    const nearDecision = near.decide(inputs({ tiles: NEAR_FAR_TILES }))
    expect(farDecision.target!.x).toBe(700)
    expect(nearDecision.target!.x).toBe(150)
  })

  it('行为配置落盘：宠物记录经配置迁移往返后 behavior 全字段保留', () => {
    const behavior = {
      enabled: false, activity: 0.8, restChance: 0.4, mouseBias: 0.2, exploreRadius: 640,
      idleMinMs: 500, idleMaxMs: 2000, restMinMs: 1000, restMaxMs: 4000,
    }
    const raw = { ...defaultConfig(), pets: [{ id: 'p1', behavior }] }
    const { config } = parseConfigText(JSON.stringify(raw))
    expect(config.pets[0]?.behavior).toEqual(behavior)
  })

  it('enabled=false 只待机不出目标', () => {
    const controller = steadyController({ enabled: false })
    const decision = controller.decide(inputs({ tiles: NEAR_FAR_TILES }))
    expect(decision.intent).toBe('idle')
    expect(decision.target).toBeNull()
  })
})

describe('块E · 决策→移动集成（瓦片世界）', () => {
  it('自主 wander 目标驱动 walk：宠物走向自己选的目标并到达', () => {
    const world = new PetWorld({ screen: SCREEN, quality: 'balanced', useL3: false, graphRebuildDelayMs: 0 })
    world.addUserSegments([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    // exploreRadius=55 使半径内唯一候选是相邻瓦片点（58px 一条 walk 边）。
    const pet = world.createPet('p1', '测试', { x: 640, y: 672 }, {
      behavior: { restChance: 0, mouseBias: 0, activity: 1, exploreRadius: 55 },
    })
    world.tick(0, 0, null)
    let sawWalk = false
    let goalSeen = false
    let goalCleared = false
    let chosen: { x: number; y: number } | null = null
    for (let index = 1; index <= 500; index += 1) {
      world.tick(index * 16, 16, null)
      const diagnostics = pet.diagnostics()
      if (diagnostics.actionId === 'walk') sawWalk = true
      if (!chosen && pet.behavior.lastDecision.target) chosen = { ...pet.behavior.lastDecision.target }
      if (pet.currentGoal) goalSeen = true
      else if (goalSeen) goalCleared = true
      if (sawWalk && goalCleared) break
    }
    expect(chosen).not.toBeNull()
    expect(goalSeen).toBe(true)
    expect(sawWalk).toBe(true)
    expect(goalCleared).toBe(true)
    expect(Math.hypot(pet.body.x - chosen!.x, pet.body.y - chosen!.y)).toBeLessThanOrEqual(40)
  })

  it('自主休息决策驱动 rest 动作', () => {
    const world = new PetWorld({ screen: SCREEN, quality: 'balanced', useL3: false, graphRebuildDelayMs: 0 })
    world.addUserSegments([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const pet = world.createPet('p1', '测试', { x: 640, y: 672 }, { behavior: { restChance: 1 } })
    world.tick(0, 0, null)
    let sawRest = false
    for (let index = 1; index <= 10 && !sawRest; index += 1) {
      world.tick(index * 16, 16, null)
      if (pet.diagnostics().actionId === 'rest') sawRest = true
    }
    expect(sawRest).toBe(true)
  })

  it('多边 walk 路径完整走到真实终点（回归：最后一段瞄准曾被中间路标覆盖）', () => {
    const world = new PetWorld({ screen: SCREEN, quality: 'balanced', useL3: false, graphRebuildDelayMs: 0 })
    world.addUserSegments([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const pet = world.createPet('p1', '测试', { x: 640, y: 672 }, {
      behavior: { restChance: 0, mouseBias: 0, activity: 1, exploreRadius: 300 },
    })
    world.tick(0, 0, null)
    let chosen: { x: number; y: number } | null = null
    let goalCleared = false
    for (let index = 1; index <= 900; index += 1) {
      world.tick(index * 16, 16, null)
      if (!chosen && pet.behavior.lastDecision.target) chosen = { ...pet.behavior.lastDecision.target }
      if (chosen && !pet.currentGoal) { goalCleared = true; break }
    }
    expect(chosen).not.toBeNull()
    expect(goalCleared).toBe(true)
    expect(Math.hypot(pet.body.x - chosen!.x, pet.body.y - chosen!.y)).toBeLessThanOrEqual(TILE_SIZE)
  })

  it('实例与世界的配置装配：settings.behavior / updateSettings 都能生效', () => {
    const settings = { ...createDefaultSettings('p1', '测试'), behavior: { activity: 0.9, restChance: 0.1 } }
    const pet = new PetInstance(settings, { x: 0, y: 0 })
    expect(pet.behavior.config.activity).toBe(0.9)
    pet.updateSettings({ behavior: { exploreRadius: 123 } })
    expect(pet.behavior.config.exploreRadius).toBe(123)
    const world = new PetWorld({ screen: SCREEN, quality: 'balanced', useL3: false, graphRebuildDelayMs: 0 })
    const created = world.createPet('p2', '测试2', { x: 100, y: 100 }, { behavior: { restChance: 1 } })
    expect(created.behavior.config.restChance).toBe(1)
  })
})
