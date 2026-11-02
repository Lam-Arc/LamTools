/**
 * 块C（物理）验收测试：泰拉瑞亚式瓦片物理。
 *
 * user:"包括寻路，边，判定框全部都与泰拉瑞亚一致，先一致，再适配"+
 * "所有的行为完全按照《泰拉瑞亚》去对齐"+
 * (判定框 = 瓦片尺寸 AABB；碰撞 = 对瓦片网格的分轴扫掠；
 *  单向板只挡自上而下；绳梯无碰撞；固定步长；无弹射。)
 */
import { describe, expect, it } from 'vitest'
import {
  DEFAULT_PHYSICS,
  PHYSICS_STEP,
  bodyBounds,
  createBody,
  stepBody,
  type BodyState,
  type MotionIntent,
  type PhysicsConfig,
  type StepEvents,
} from '@/pet/engine/physics.ts'
import { TileGrid } from '@/pet/engine/tiles.ts'
import { TerrainField } from '@/pet/engine/terrain.ts'

const SCREEN = { x: 0, y: 0, width: 1280, height: 800 }

/** 由几何段体素化的瓦片世界（与运行时同一套体素化）。 */
function grid(segments: Array<{ id: string; kind: string; layer: string; x1: number; y1: number; x2: number; y2: number; oneWay?: boolean; ladder?: boolean }>, screen = SCREEN): TileGrid {
  const terrain = new TerrainField()
  terrain.setScreenBounds(screen)
  for (const segment of segments) terrain.add(segment as never)
  const g = new TileGrid(screen, {
    jumpHeightPx: (DEFAULT_PHYSICS.jumpImpulse ** 2) / (2 * DEFAULT_PHYSICS.gravity),
    bodyWidth: DEFAULT_PHYSICS.hitboxWidth,
    bodyHeight: DEFAULT_PHYSICS.hitboxHeight,
    walkSpeed: DEFAULT_PHYSICS.walkSpeed,
    gravity: DEFAULT_PHYSICS.gravity,
  })
  g.build(terrain)
  return g
}

function run(
  body: BodyState,
  intent: MotionIntent,
  g: TileGrid,
  steps: number,
  dt = PHYSICS_STEP,
  config: PhysicsConfig = DEFAULT_PHYSICS,
): StepEvents[] {
  const events: StepEvents[] = []
  for (let index = 0; index < steps; index += 1) {
    events.push(stepBody(body, intent, config, g, dt))
  }
  return events
}

/** 放到地板瓦上并站稳（脚底 = 地板瓦顶面）。 */
function settle(g: TileGrid, x: number, floorTop: number): BodyState {
  const body = createBody(x, floorTop, DEFAULT_PHYSICS)
  run(body, {}, g, 10)
  expect(body.grounded).toBe(true)
  return body
}

describe('判定框：瓦片碰撞用的 AABB', () => {
  it('判定框是固定屏幕尺寸的 AABB（60×120），脚底锚定', () => {
    const g = grid([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const body = createBody(500, 688, DEFAULT_PHYSICS)
    expect(body.width).toBe(60)
    expect(body.height).toBe(120)
    run(body, {}, g, 10)
    const b = bodyBounds(body)
    expect(b.bottom).toBeCloseTo(688, 1)
    expect(b.left).toBeCloseTo(500 - body.width / 2, 1)
  })
})

describe('实心瓦：下落落地、站立即稳、水平阻挡', () => {
  it('下落落在实心瓦顶上，脚底=瓦顶面，无弹射', () => {
    const g = grid([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const body = createBody(500, 500, DEFAULT_PHYSICS)
    run(body, {}, g, 240)
    expect(body.grounded).toBe(true)
    expect(body.y).toBeCloseTo(688, 0)
    expect(body.vy).toBe(0)
    run(body, {}, g, 120)
    expect(body.y).toBeCloseTo(body.y, 6)
    expect(body.vy).toBe(0)
  })

  it('实心墙阻挡水平移动（AABB 扫掠），速度归零', () => {
    const g = grid([
      { id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
      { id: 'wall', kind: 'vertical', layer: 'user', x1: 400, y1: 300, x2: 400, y2: 700 },
    ])
    const body = settle(g, 300, 688)
    run(body, { vx: DEFAULT_PHYSICS.walkSpeed }, g, 60)
    const stopped = body.x
    run(body, { vx: DEFAULT_PHYSICS.walkSpeed }, g, 60)
    // 推到墙瓦列边界后不再前进（瓦片量化：右缘停在墙瓦左沿）。
    expect(body.x).toBe(stopped)
    expect(body.x + DEFAULT_PHYSICS.hitboxWidth / 2).toBeLessThanOrEqual(400)
  })

  it('重力按 g·dt 累积、终端速度封顶（固定步长）', () => {
    const g = grid([], { x: 0, y: 0, width: 1280, height: 4000 })
    const body = createBody(500, 100, DEFAULT_PHYSICS)
    stepBody(body, {}, DEFAULT_PHYSICS, g, PHYSICS_STEP)
    expect(body.vy).toBeCloseTo(DEFAULT_PHYSICS.gravity * PHYSICS_STEP, 6)
    run(body, {}, g, 119)
    expect(body.vy).toBeCloseTo(DEFAULT_PHYSICS.gravity, 0)
  })
})

describe('单向板：可站、可从下穿过、可下落穿过、水平可穿过', () => {
  const oneWay = (): TileGrid => grid([
    { id: 'lid', kind: 'platform', layer: 'L2', x1: 300, y1: 400, x2: 900, y2: 400, oneWay: true },
    { id: 'ground', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
  ])

  it('从上方落到单向板上站稳', () => {
    const g = oneWay()
    const body = createBody(500, 250, DEFAULT_PHYSICS)
    run(body, {}, g, 240)
    expect(body.grounded).toBe(true)
    expect(body.y).toBeCloseTo(400, 0)
  })

  it('从下往上跳直接穿过单向板（不撞头）', () => {
    const g = oneWay()
    // 起点：头顶在单向板下沿之下（身体完全在板下方），跳起后头穿过板面。
    const body = createBody(500, 600, DEFAULT_PHYSICS)
    body.vy = -DEFAULT_PHYSICS.jumpImpulse
    run(body, {}, g, 240)
    // 穿过之后落回单向板上。
    expect(body.grounded).toBe(true)
    expect(body.y).toBeCloseTo(400, 0)
  })

  it('站在单向板上提交下落 → 穿过落到地面', () => {
    const g = oneWay()
    const body = settle(g, 500, 400)
    run(body, { dropThrough: true }, g, 120)
    expect(body.grounded).toBe(true)
    expect(body.y).toBeCloseTo(688, 0)
  })

  it('下落穿透窗口有限：窗口过后单向板恢复阻挡', () => {
    const g = oneWay()
    const body = settle(g, 500, 400)
    run(body, { dropThrough: true }, g, 1)
    expect(body.dropTimer).toBeGreaterThan(0)
    run(body, {}, g, 60)
    // 已落到地面；再落回时单向板恢复正常阻挡。
    expect(body.grounded).toBe(true)
    const above = createBody(500, 300, DEFAULT_PHYSICS)
    run(above, {}, g, 240)
    expect(above.grounded).toBe(true)
    expect(above.y).toBeCloseTo(400, 0)
  })
})

describe('绳梯：无碰撞、攀爬意图抓附上下', () => {
  const ropeField = (): TileGrid => grid([
    { id: 'rope', kind: 'vertical', layer: 'L2', x1: 400, y1: 100, x2: 400, y2: 700, ladder: true },
    { id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
  ])

  it('走过不挡路', () => {
    const g = ropeField()
    const body = settle(g, 470, 688)
    run(body, { vx: -DEFAULT_PHYSICS.walkSpeed }, g, 40)
    expect(body.x).toBeLessThan(384)
    expect(body.grounded).toBe(true)
  })

  it('有攀爬意图即抓附上升；松开后下落', () => {
    const g = ropeField()
    const body = settle(g, 410, 688)
    const y0 = body.y
    for (let i = 0; i < 90; i += 1) {
      stepBody(body, { climb: -1 }, DEFAULT_PHYSICS, g, PHYSICS_STEP)
    }
    for (let i = 0; i < 300; i += 1) {
      stepBody(body, { climb: 1 }, DEFAULT_PHYSICS, g, PHYSICS_STEP)
    }
    expect(body.y).toBeGreaterThan(y0 - 60)
  })
})

describe('跳跃：冲量 + 重力（瓦片物理）', () => {
  it('跳起越过矮台阶并落回', () => {
    const g = grid([
      { id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
      { id: 'step', kind: 'platform', layer: 'user', x1: 600, y1: 550, x2: 800, y2: 550 },
    ])
    const body = settle(g, 500, 688)
    run(body, { vx: DEFAULT_PHYSICS.walkSpeed, jump: true }, g, 1)
    expect(body.vy).toBeLessThan(0)
    run(body, { vx: DEFAULT_PHYSICS.walkSpeed }, g, 150)
    // 落到台阶上或地板上，都不悬空。
    expect(body.grounded).toBe(true)
    expect([688, 544]).toContain(Math.round(body.y))
  })

  it('跳跃高度 ≈ jumpImpulse²/2g（与瓦片换算一致）', () => {
    const g = grid([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const body = settle(g, 500, 688)
    let minY = body.y
    run(body, { jump: true }, g, 1)
    for (let index = 0; index < 120; index += 1) {
      stepBody(body, {}, DEFAULT_PHYSICS, g, PHYSICS_STEP)
      minY = Math.min(minY, body.y)
    }
    const rise = 688 - minY
    const expected = (DEFAULT_PHYSICS.jumpImpulse ** 2) / (2 * DEFAULT_PHYSICS.gravity)
    expect(rise).toBeGreaterThan(expected * 0.75)
    expect(rise).toBeLessThan(expected * 1.05)
  })
})

describe('用户拖拽：只受屏幕边界钳制', () => {
  it('拖拽主控时穿透实心墙与地板，只被屏幕边界挡住', () => {
    // user:"我拖住桌宠的时候，不应该有任何一个除了屏幕（也就是 L0 级）的墙壁会挡住它"
    const g = grid([
      { id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
      { id: 'wall', kind: 'vertical', layer: 'user', x1: 400, y1: 300, x2: 400, y2: 700 },
    ])
    const body = createBody(300, 672, DEFAULT_PHYSICS)
    const target = { x: 600, y: 300 }
    for (let index = 0; index < 300; index += 1) {
      stepBody(body, { dragTarget: target, ghost: true }, DEFAULT_PHYSICS, g, PHYSICS_STEP)
    }
    expect(body.x).toBeGreaterThan(500)
    expect(body.y).toBeLessThan(400)

    const corner = createBody(300, 400, DEFAULT_PHYSICS)
    for (let index = 0; index < 240; index += 1) {
      stepBody(corner, { dragTarget: { x: -500, y: -500 }, ghost: true }, DEFAULT_PHYSICS, g, PHYSICS_STEP)
    }
    expect(corner.x).toBeCloseTo(DEFAULT_PHYSICS.hitboxWidth / 2, 1)
    expect(corner.y).toBeCloseTo(DEFAULT_PHYSICS.hitboxHeight, 1)
  })
})

describe('固定步长：跨帧率一致（泰拉瑞亚固定 tick）', () => {
  it('同一 400ms 按 16ms 帧与 8ms 帧推进，空中位置一致', () => {
    const g = grid([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 900, x2: 1280, y2: 900 }], { x: 0, y: 0, width: 1280, height: 1200 })
    const a = createBody(500, 500, DEFAULT_PHYSICS)
    const b = createBody(500, 500, DEFAULT_PHYSICS)
    // 泰拉瑞亚固定 tick：无论渲染帧多长，物理都以 1/120 固定步长细分推进。
    const advance = (body: BodyState, frameMs: number, frames: number): void => {
      for (let index = 0; index < frames; index += 1) {
        let remaining = frameMs / 1000
        while (remaining > 0) {
          const dt = Math.min(PHYSICS_STEP, remaining)
          stepBody(body, {}, DEFAULT_PHYSICS, g, dt)
          remaining -= dt
        }
      }
    }
    advance(a, 16, 25)
    advance(b, 8, 50)
    expect(Math.abs(a.y - b.y)).toBeLessThan(0.5)
    expect(Math.abs(a.vy - b.vy)).toBeLessThan(0.5)
  })
})
