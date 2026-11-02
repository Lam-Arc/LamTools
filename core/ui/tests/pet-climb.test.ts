/**
 * 爬墙回归：各种起点/目标组合下，宠物都必须走到或明确判定不可达，不能卡住。
 *
 * user:"有时候爬墙会卡住"+
 * (卡住的根因都在"规划说能跳/能爬、执行却做的另一件事"：跳跃边水平射程没有按
 *  真实弹道算、攀爬/跳跃动作被重复请求时完成状态不重置、执行器里攀爬动作不在
 *  梯子上也不让位。这里用实验室同款窗口几何批量跑，任何组合停滞 2 秒即失败。)
 */
import { describe, expect, it } from 'vitest'
import { PetWorld } from '@/pet/engine/world.ts'

const SCREEN = { x: 0, y: 0, width: 1600, height: 900 }

function makeWorld(): PetWorld {
  const world = new PetWorld({ screen: SCREEN, quality: 'balanced', useL3: false, graphRebuildDelayMs: 0 })
  world.applyWindows([
    { id: 'w1', title: 'A', className: 'Synthetic', bounds: { x: 220, y: 420, width: 520, height: 260 }, z: 0 },
    { id: 'w2', title: 'B', className: 'Synthetic', bounds: { x: 820, y: 360, width: 420, height: 260 }, z: 1 },
  ])
  world.tick(0, 0, null)
  return world
}

/** 走到目标（或明确不可达）；停滞超过 2 秒判为卡住。 */
function run(from: { x: number; y: number }, to: { x: number; y: number }): 'ok' | 'unreachable' | string {
  const world = makeWorld()
  const pet = world.createPet('p', 'P', from, { behavior: { enabled: false } })
  world.tick(0, 0, null)
  if (pet.setDestination(to, { tiles: world.tileGrid, now: 0 }) === 'unreachable') return 'unreachable'
  let last = { x: pet.body.x, y: pet.body.y }
  let stillMs = 0
  for (let index = 1; index <= 2400; index += 1) {
    world.tick(index * 16, 16, null)
    if (!pet.currentGoal) return 'ok'
    const moved = Math.hypot(pet.body.x - last.x, pet.body.y - last.y)
    stillMs = moved < 0.2 ? stillMs + 16 : 0
    last = { x: pet.body.x, y: pet.body.y }
    if (stillMs >= 2000) {
      const d = pet.diagnostics()
      return `STUCK ${JSON.stringify({ x: +pet.body.x.toFixed(1), y: +pet.body.y.toFixed(1), act: d.actionId, path: `${d.pathIndex}/${d.pathNodes}`, climbing: d.climbing, grounded: d.grounded, hung: d.hung })}`
    }
  }
  return 'timeout'
}

describe('爬墙压力回归', () => {
  it('所有起点/目标组合都能到达或明确不可达，不卡住', () => {
    const spawns = [
      { x: 800, y: 896 },
      { x: 250, y: 896 },
      { x: 1280, y: 896 },
      { x: 500, y: 672 },
      { x: 1000, y: 672 },
      { x: 296, y: 688 },
      { x: 900, y: 628 },
    ]
    const targets = [
      { x: 480, y: 420 }, { x: 480, y: 672 }, { x: 300, y: 420 }, { x: 1000, y: 360 },
      { x: 1000, y: 612 }, { x: 200, y: 20 }, { x: 900, y: 20 }, { x: 1200, y: 20 },
      { x: 600, y: 300 }, { x: 1100, y: 680 }, { x: 260, y: 680 }, { x: 900, y: 420 },
    ]
    const bad: string[] = []
    for (const from of spawns) {
      for (const to of targets) {
        const result = run(from, to)
        if (result !== 'ok' && result !== 'unreachable') bad.push(`(${from.x},${from.y})→(${to.x},${to.y}): ${result}`)
      }
    }
    expect(bad, bad.slice(0, 8).join('\n')).toEqual([])
  })
})
