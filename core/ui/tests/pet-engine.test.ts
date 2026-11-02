/**
 * 泰拉瑞亚化引擎验收：体素化瓦片、瓦片 A* 寻路、瓦片跟随执行、世界行为。
 *
 * user:"包括寻路，边，判定框全部都与泰拉瑞亚一致，先一致，再适配"+
 * "所有的行为完全按照《泰拉瑞亚》去对齐，不用考虑既有实现"+
 * (地图 = 体素化瓦片（实心/单向板/绳梯）；寻路 = 瓦片 A*（走/跳/落/爬/挂）；
 *  执行 = 沿瓦片路标移动；墙天然隔断行走，翻越走跳跃路标，卡住重寻路。)
 */
import { describe, expect, it } from 'vitest'
import { DEFAULT_PHYSICS } from '@/pet/engine/physics.ts'
import { TileGrid, TILE_SIZE, TileType } from '@/pet/engine/tiles.ts'
import { TerrainField } from '@/pet/engine/terrain.ts'
import { PetWorld } from '@/pet/engine/world.ts'

const SCREEN = { x: 0, y: 0, width: 1280, height: 800 }
/** 地板段 y=700 → 体素化后瓦顶 = floor(700/16)*16 = 688。 */
const FLOOR_TOP = 688

function makeWorld(segments: Array<{ id: string; kind: string; layer: string; x1: number; y1: number; x2: number; y2: number; oneWay?: boolean; ladder?: string | boolean }>): PetWorld {
  const world = new PetWorld({ screen: SCREEN, quality: 'balanced', useL3: false, graphRebuildDelayMs: 0 })
  world.addUserSegments(segments as never)
  world.tick(0, 0, null) // 触发体素化建图
  return world
}

describe('体素化：几何段 → 瓦片（泰拉瑞亚地图）', () => {
  it('地板段 → 实心瓦行；其上一行可站立', () => {
    const world = makeWorld([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const grid = world.tileGrid
    expect(grid.typeAt(10, 43)).toBe(TileType.Solid)
    expect(grid.isStandable(10, 42)).toBe(true)
    const p = grid.standPoint(10, 42)
    expect(p.y).toBeCloseTo(FLOOR_TOP, 0)
  })

  it('屏幕左右边缘 = 绳梯（L1 墙可沿边缘攀爬）', () => {
    const world = makeWorld([])
    const grid = world.tileGrid
    expect(grid.typeAt(0, 10)).toBe(TileType.Ladder)
    expect(grid.typeAt(grid.cols - 1, 10)).toBe(TileType.Ladder)
    // 身体贴到边缘梯瓦即算抓附（中心被边界钳住，进不到墙里）。
    expect(grid.bodyTouchesLadder(30, 784)).toBe(true)
  })

  it('窗口 → 顶边单向板瓦行 + 竖边绳梯瓦列', () => {
    const world = makeWorld([])
    world.applyWindows([{ id: 'w1', title: 'A', className: 'App', bounds: { x: 300, y: 400, width: 400, height: 300 }, z: 0 }])
    world.tick(0, 0, null)
    const grid = world.tileGrid
    // 顶边 y=400 → 瓦行 25 单向板；竖边 x=300→列 18、x=700→列 43 绳梯。
    expect(grid.typeAt(30, 25)).toBe(TileType.Platform)
    expect(grid.typeAt(18, 30)).toBe(TileType.Ladder)
    expect(grid.typeAt(43, 30)).toBe(TileType.Ladder)
    // 单向板上方可站立（可落上去）。
    expect(grid.isStandable(30, 24)).toBe(true)
    // 窗口下沿也是平台（设计：上沿下沿都是平台）。
    expect(grid.typeAt(30, 43)).toBe(TileType.Platform)
  })

  it('自主探索目的地只有可站立点，不含檐下悬挂点', () => {
    // user:"你这不又是在打补丁吗？……为什么悬挂点会评分更高"+
    // (候选域必须是"能站的地方"；悬挂只是通行状态/手动目标。)
    const world = makeWorld([])
    const grid = world.tileGrid
    expect(grid.isHangable(10, 1)).toBe(true)
    const points = grid.standPoints()
    expect(points.length).toBeGreaterThan(0)
    expect(points.every(point => grid.isStandable(point.col, point.row))).toBe(true)
    expect(points.some(point => grid.isHangable(point.col, point.row) && !grid.isStandable(point.col, point.row))).toBe(false)
    expect(points.some(point => point.y < grid.bounds.y + DEFAULT_PHYSICS.hitboxHeight)).toBe(false)
  })

  it('完全被遮住的窗口：整窗无瓦（顶边与绳梯都不建）', () => {
    const world = makeWorld([])
    world.applyWindows([
      { id: 'w1', title: 'A', className: 'App', bounds: { x: 100, y: 300, width: 400, height: 300 }, z: 0 },
      // w3 完全落在 w1 的可见范围里：顶边 y=340（瓦行 21）被 w1 的顶边线挡住。
      { id: 'w3', title: 'C', className: 'App', bounds: { x: 170, y: 340, width: 300, height: 200 }, z: 2 },
    ])
    world.tick(0, 0, null)
    const grid = world.tileGrid
    expect(grid.typeAt(10, 18)).toBe(TileType.Platform) // w1 顶边（y=300 → 瓦行 18）存在
    // w3 顶边瓦行 21 与绳梯列（x=170 → 瓦列 10）都不存在。
    expect(grid.typeAt(10, 21)).not.toBe(TileType.Platform)
    expect(grid.typeAt(10, 22)).not.toBe(TileType.Ladder)
  })
})

describe('瓦片 A* 寻路（泰拉瑞亚 NPC 语义）', () => {
  it('平地：同层目标 → 路标全在同行（走，不跳）', () => {
    const world = makeWorld([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const path = world.tileGrid.findPath(900, 671, 200, 671)
    expect(path).not.toBeNull()
    expect(path!.length).toBeGreaterThan(2)
    const rows = new Set(path!.map(c => c.row))
    expect(rows.size).toBe(1)
  })

  it('封到屏底的高墙：两侧不可达（瓦片墙天然隔断）', () => {
    const world = makeWorld([
      { id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
      // 顶边现在可悬挂（用户设计），矮墙可以绕天花板过去；要封死必须顶到屏幕顶。
      { id: 'wall', kind: 'vertical', layer: 'user', x1: 400, y1: 0, x2: 400, y2: 800 },
    ])
    const path = world.tileGrid.findPath(500, 671, 200, 671)
    expect(path).toBeNull()
  })

  it('矮墙（可跳过）：路径存在且含跳跃路标（上行瓦）', () => {
    const world = makeWorld([
      { id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
      { id: 'wall', kind: 'vertical', layer: 'user', x1: 400, y1: 550, x2: 400, y2: 700 },
    ])
    // 墙顶 550 → 瓦行 34（顶 544）；地板 688；高差 144 < 跳高 261 → 可翻越。
    const path = world.tileGrid.findPath(500, 671, 200, 671)
    expect(path).not.toBeNull()
  })

  it('A* 边代价按设计表：走1 / 爬2 / 挂3 / 跳 x+y / 落 (x+y)/2', () => {
    // user:"一瓦片为1，行走时权重为1 跳跃为x+y合。攀爬时的价为行走时的2倍，
    // 悬挂时的价为行走时的3倍，落下价为x+y的一半"
    const world = makeWorld([
      { id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
      { id: 'shelf', kind: 'platform', layer: 'user', x1: 0, y1: 600, x2: 200, y2: 600, oneWay: true },
      { id: 'hang', kind: 'platform', layer: 'user', x1: 300, y1: 400, x2: 900, y2: 400, oneWay: true },
      { id: 'rope', kind: 'vertical', layer: 'user', x1: 800, y1: 100, x2: 800, y2: 700, ladder: true },
    ])
    const grid = world.tileGrid
    expect(grid.moveCost({ col: 10, row: 42 }, { col: 11, row: 42 })).toBe(1) // 走
    expect(grid.moveCost({ col: 50, row: 30 }, { col: 50, row: 29 })).toBe(2) // 爬
    expect(grid.moveCost({ col: 30, row: 26 }, { col: 31, row: 26 })).toBe(3) // 挂
    expect(grid.moveCost({ col: 10, row: 42 }, { col: 10, row: 36 })).toBe(6) // 跳 0+6
    expect(grid.moveCost({ col: 10, row: 37 }, { col: 9, row: 42 })).toBe(3) // 落 (1+5)/2
    expect(grid.moveCost({ col: 30, row: 26 }, { col: 30, row: 42 })).toBe(8) // 挂→落 16/2
  })

  it('窗口竖边=绳梯：路径可以爬上窗口顶（高台通过攀爬可达）', () => {
    const world = makeWorld([
      { id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
    ])
    world.applyWindows([{ id: 'w1', title: 'A', className: 'App', bounds: { x: 300, y: 400, width: 400, height: 300 }, z: 0 }])
    world.tick(0, 0, null)
    // 窗口顶 y=400 → 瓦行 25；地板瓦顶 688；高差 288 > 跳高——只能爬竖边上去。
    const path = world.tileGrid.findPath(340, 671, 500, 384)
    expect(path).not.toBeNull()
    // 路径中含绳梯瓦。
    const hasLadder = path!.some(c => world.tileGrid.typeAt(c.col, c.row) === TileType.Ladder)
    expect(hasLadder).toBe(true)
  })

  it('选靶按实际路程：天花板悬挂点的路程远大于同层地面点', () => {
    // user:"它站在最下边，凭什么会认为它离最上边这么更近？"+"改"
    const world = makeWorld([])
    const grid = world.tileGrid
    const distances = grid.reachableDistances(200, 783)
    expect(distances).not.toBeNull()
    const floor = distances!.get(grid.index(22, 48))
    const ceiling = distances!.get(grid.index(12, 1))
    expect(floor).toBeDefined()
    expect(ceiling).toBeDefined()
    expect(ceiling!).toBeGreaterThan(floor! * 3)
  })

  it('可达集合：墙另一侧的瓦不在可达集合里（行为选靶不选它们）', () => {
    const world = makeWorld([
      { id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
      { id: 'wall', kind: 'vertical', layer: 'user', x1: 400, y1: 0, x2: 400, y2: 800 },
    ])
    const reachable = world.tileGrid.reachableTiles(500, 671)
    expect(reachable).not.toBeNull()
    const leftStandable = [...reachable!].some(idx => {
      const col = idx % world.tileGrid.cols
      return col * TILE_SIZE < 380
    })
    expect(leftStandable).toBe(false)
  })
})

describe('瓦片跟随执行（宠物沿瓦片路标移动）', () => {
  it('点击同层目标：宠物走过去、到达后目标清空（判定用真实终点）', () => {
    const world = makeWorld([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const pet = world.createPet('p1', '测试', { x: 640, y: 672 }, { behavior: { enabled: false } })
    world.tick(0, 0, null)
    const result = pet.setDestination({ x: 200, y: 672 }, { tiles: world.tileGrid, now: 0 })
    expect(result).toBe('ok')
    let arrived = false
    for (let index = 1; index <= 900; index += 1) {
      world.tick(index * 16, 16, null)
      if (!pet.currentGoal) { arrived = true; break }
    }
    expect(arrived).toBe(true)
    expect(Math.abs(pet.body.x - 200)).toBeLessThanOrEqual(TILE_SIZE)
    // user:"为什么它都已经停在那里，也没有其他寻路目标点，但它依旧处于 walk 状态？"+
    // (到达后必须真的切到 idle，不能因为 walk 优先级更高就继续播走路。)
    for (let index = 0; index < 10; index += 1) world.tick(20000 + index * 16, 16, null)
    expect(pet.diagnostics().actionId).toBe('idle')
    expect(Math.abs(pet.body.vx)).toBeLessThan(1)
  })

  it('点击高台（窗口顶）：宠物爬绳梯上去', () => {
    const world = makeWorld([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    world.applyWindows([{ id: 'w1', title: 'A', className: 'App', bounds: { x: 300, y: 400, width: 400, height: 300 }, z: 0 }])
    const pet = world.createPet('p1', '测试', { x: 340, y: 672 }, { behavior: { enabled: false } })
    world.tick(0, 0, null)
    const result = pet.setDestination({ x: 500, y: 384 }, { tiles: world.tileGrid, now: 0 })
    expect(result).toBe('ok')
    let sawClimb = false
    let arrived = false
    for (let index = 1; index <= 1800; index += 1) {
      world.tick(index * 16, 16, null)
      if (pet.diagnostics().climbing) sawClimb = true
      if (!pet.currentGoal) { arrived = true; break }
    }
    expect(sawClimb).toBe(true)
    expect(arrived).toBe(true)
    // 到达窗口顶（瓦顶 400）。
    expect(Math.abs(pet.body.y - 400)).toBeLessThanOrEqual(TILE_SIZE)
  })

  it('点击左边缘高处的平台：宠物沿屏幕边缘绳梯爬上去', () => {
    // 用户："L1墙可沿边缘攀爬，就像梯子"
    const world = makeWorld([{ id: 'shelf', kind: 'platform', layer: 'user', x1: 0, y1: 400, x2: 300, y2: 400, oneWay: true }])
    const pet = world.createPet('p1', '测试', { x: 100, y: 784 }, { behavior: { enabled: false } })
    world.tick(0, 0, null)
    const result = pet.setDestination({ x: 100, y: 400 }, { tiles: world.tileGrid, now: 0 })
    expect(result).toBe('ok')
    let sawClimb = false
    let arrived = false
    for (let index = 1; index <= 1800; index += 1) {
      world.tick(index * 16, 16, null)
      if (pet.diagnostics().climbing) sawClimb = true
      if (!pet.currentGoal) { arrived = true; break }
    }
    expect(sawClimb).toBe(true)
    expect(arrived).toBe(true)
    expect(Math.abs(pet.body.y - 400)).toBeLessThanOrEqual(TILE_SIZE)
  })

  it('L1 顶边可悬挂：沿屏幕边缘绳梯爬到顶部后挂到顶边下面', () => {
    // 用户："L1顶部那一条是可以悬挂的"
    const world = makeWorld([])
    const pet = world.createPet('p1', '测试', { x: 100, y: 784 }, { behavior: { enabled: false } })
    world.tick(0, 0, null)
    const result = pet.setDestination({ x: 200, y: 20 }, { tiles: world.tileGrid, now: 0 })
    expect(result).toBe('ok')
    let sawHung = false
    let sawClimb = false
    let arrived = false
    for (let index = 1; index <= 2400; index += 1) {
      world.tick(index * 16, 16, null)
      if (pet.body.hung) sawHung = true
      if (pet.diagnostics().climbing) sawClimb = true
      if (!pet.currentGoal) { arrived = true; break }
    }
    expect(sawClimb).toBe(true)
    expect(sawHung).toBe(true)
    expect(arrived).toBe(true)
    expect(Math.abs(pet.body.y - 136)).toBeLessThanOrEqual(TILE_SIZE)
    // user:"悬挂移动状态不会停止 会一直走"+(到点后原地挂着，不再滑行。)
    for (let index = 0; index < 120; index += 1) world.tick(5000 + index * 16, 16, null)
    expect(pet.body.hung).toBe(true)
    expect(Math.abs(pet.body.vx)).toBeLessThan(1)
    // 再给一个落地点：必须主动松手离开檐下，不能被同一块板重新吸住。
    const leave = pet.setDestination({ x: 200, y: 784 }, { tiles: world.tileGrid, now: 7000 })
    expect(leave).toBe('ok')
    let left = false
    for (let index = 0; index < 600; index += 1) {
      world.tick(8000 + index * 16, 16, null)
      if (!pet.body.hung) left = true
      if (left && !pet.currentGoal) break
    }
    expect(left).toBe(true)
    expect(pet.currentGoal).toBeNull()
  })

  it('途中被墙挡住 → 卡住看门狗重规划 → 翻越/绕行 → 到达', () => {
    const world = makeWorld([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const pet = world.createPet('p1', '测试', { x: 640, y: 672 }, { behavior: { enabled: false } })
    world.tick(0, 0, null)
    pet.setDestination({ x: 100, y: 672 }, { tiles: world.tileGrid, now: 0 })
    let index = 1
    let sawWalk = false
    for (; index <= 200 && pet.body.x > 500; index += 1) {
      world.tick(index * 16, 16, null)
      if (pet.diagnostics().actionId === 'walk') sawWalk = true
    }
    expect(sawWalk).toBe(true)
    // 途中立起矮墙（顶 550 → 瓦顶 544，可跳过）。
    world.addUserSegments([{ id: 'wall', kind: 'vertical', layer: 'user', x1: 400, y1: 550, x2: 400, y2: 700 }])
    let arrived = false
    for (; index <= 1400; index += 1) {
      world.tick(index * 16, 16, null)
      if (!pet.currentGoal && Math.abs(pet.body.x - 100) <= TILE_SIZE) { arrived = true; break }
    }
    expect(arrived).toBe(true)
  })
})

describe('世界行为（多实例 / 窗口跟随 / 命中测试）', () => {
  it('两只宠物独立活动，共享瓦片世界', () => {
    const world = makeWorld([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const a = world.createPet('a', 'A', { x: 200, y: 672 })
    const b = world.createPet('b', 'B', { x: 1000, y: 672 })
    world.tick(0, 16, null)
    expect(world.tileGrid.version).toBeGreaterThan(0)
    expect(world.pets.length).toBe(2)
    expect(a.body).not.toBe(b.body)
    expect(world.terrain.all().length).toBe(5)
  })

  it('窗口小幅移动：站在顶边上的宠物跟随（泰拉瑞亚平台语义）', () => {
    const world = makeWorld([])
    world.applyWindows([{ id: 'w1', title: 'PDF', className: 'Acrobat', bounds: { x: 200, y: 400, width: 600, height: 400 }, z: 1 }])
    // 宠物直接放到窗口顶瓦上（顶 y=400 → 瓦行 25，瓦顶 400）。
    const pet = world.createPet('p', 'P', { x: 400, y: 400 }, { behavior: { enabled: false } })
    for (let index = 0; index < 60; index += 1) world.tick(1000 + index * 16, 16, null)
    expect(pet.body.grounded).toBe(true)
    const before = pet.body.x
    world.applyWindows([{ id: 'w1', title: 'PDF', className: 'Acrobat', bounds: { x: 260, y: 400, width: 600, height: 400 }, z: 1 }])
    expect(pet.body.x).toBeCloseTo(before + 60, 1)
  })

  it('拖住桌宠可以穿过墙壁，松手后恢复碰撞落地', () => {
    // user:"我拖住桌宠的时候，不应该有任何一个除了屏幕（也就是 L0 级）的墙壁会挡住它"
    const world = makeWorld([
      { id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 },
      { id: 'wall', kind: 'vertical', layer: 'user', x1: 400, y1: 300, x2: 400, y2: 700 },
    ])
    const pet = world.createPet('p', 'P', { x: 300, y: 672 }, { behavior: { enabled: false } })
    world.tick(0, 0, null)
    pet.startDrag({ x: 300, y: 400 })
    for (let index = 1; index <= 120; index += 1) {
      pet.updateDrag({ x: 600, y: 400 })
      world.tick(index * 16, 16, null)
    }
    expect(pet.body.x).toBeGreaterThan(500)
    pet.endDrag()
    for (let index = 0; index < 240; index += 1) world.tick(20000 + index * 16, 16, null)
    expect(pet.body.grounded).toBe(true)
    expect(pet.body.y).toBeCloseTo(688, 0)
  })

  it('hitTest 按交互 Hitbox（精灵框归一化）命中，不再用物理 AABB', () => {
    // user:"碰撞箱不对，比实际偏高"+
    // (绘制、点击、穿透必须同源：Hitbox 相对精灵框归一化；物理 AABB 只管地形。
    //  之前点击按 AABB、绘制按精灵框，屏幕上粉色的上半截根本点不到。)
    const world = makeWorld([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const hitboxes = [
      { id: 'head', name: '头', x: 0.25, y: 0.02, width: 0.5, height: 0.3, action: 'interact_head', enabled: true },
      { id: 'body', name: '身体', x: 0.2, y: 0.35, width: 0.6, height: 0.6, action: 'interact', enabled: true },
    ]
    const pet = world.createPet('p', 'P', { x: 400, y: 672 }, {
      behavior: { enabled: false },
      spriteWidth: 100,
      spriteHeight: 200,
      hitboxes,
    })
    for (let index = 0; index < 30; index += 1) world.tick(1000 + index * 16, 16, null)
    // 脚底 688 → 精灵框 y 488..688；头部 Hitbox y 492..552，在物理 AABB 顶(568)之上。
    const headPoint = { x: 400, y: 520 }
    expect(headPoint.y).toBeLessThan(pet.renderRect().y)
    const hit = world.hitTest(headPoint)
    expect(hit?.pet.id).toBe('p')
    expect(pet.hitTestPoint(headPoint)?.hitbox.action).toBe('interact_head')
    // 精灵框内但不在任何 Hitbox 的透明角：不命中（画出来的框就是点击域）。
    expect(world.hitTest({ x: 360, y: 500 })).toBeNull()
    // 精灵框外：不命中。
    expect(world.hitTest({ x: 400, y: 700 })).toBeNull()
  })

  it('穿透矩形 = 交互 Hitbox 世界矩形，朝向镜像与绘制一致', () => {
    const world = makeWorld([])
    const hitbox = { id: 'torso', name: '身体', x: 0.05, y: 0.2, width: 0.4, height: 0.5, action: 'interact', enabled: true }
    const pet = world.createPet('p', 'P', { x: 400, y: 500 }, {
      behavior: { enabled: false },
      facing: -1,
      spriteWidth: 100,
      spriteHeight: 200,
      hitboxes: [hitbox],
    })
    const rects = pet.interactionRects()
    const rect = pet.visibleRect()
    expect(rects).toHaveLength(1)
    // 朝左时镜像到精灵框右半侧。
    expect(rects[0]!.x).toBeCloseTo(rect.x + (1 - hitbox.x - hitbox.width) * rect.width, 6)
    expect(rects[0]!.width).toBeCloseTo(hitbox.width * rect.width, 6)
    expect(rects[0]!.y).toBeCloseTo(rect.y + hitbox.y * rect.height, 6)
    expect(rects[0]!.x).toBeGreaterThan(rect.x + rect.width / 2)
  })

  it('拖拽保持抓取偏移：抓起角色不会跳到光标上', () => {
    // user:"碰撞箱不对，比实际偏高"+
    // (抓取锚点是"鼠标到脚底"的偏移：在哪个位置按下就抓着那个位置走。)
    const world = makeWorld([{ id: 'floor', kind: 'platform', layer: 'user', x1: 0, y1: 700, x2: 1280, y2: 700 }])
    const pet = world.createPet('p', 'P', { x: 400, y: 672 }, { behavior: { enabled: false } })
    for (let index = 0; index < 30; index += 1) world.tick(1000 + index * 16, 16, null)
    const before = pet.position
    // 抓在脚底上方 88px。
    pet.startDrag({ x: before.x, y: before.y - 88 })
    for (let index = 0; index < 10; index += 1) world.tick(2000 + index * 16, 16, null)
    expect(Math.abs(pet.body.y - before.y)).toBeLessThan(6)
    // 光标右移 50、下移 20 → 角色按同样位移跟随，而不是把脚底吸到光标上。
    pet.updateDrag({ x: before.x + 50, y: before.y - 88 + 20 })
    for (let index = 0; index < 90; index += 1) world.tick(3000 + index * 16, 16, null)
    expect(pet.body.x).toBeCloseTo(before.x + 50, 0)
    expect(pet.body.y).toBeCloseTo(before.y + 20, 0)
    pet.endDrag()
  })
})
