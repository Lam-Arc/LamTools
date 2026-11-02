/**
 * 渲染适配层测试：谁画、画多大、用哪段动画。
 *
 * WebGL 本身跑不了 jsdom，所以这里验证的是**决定逻辑**（纯函数）：
 * 选错渲染器或选错动画，比画不出来更难排查。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { frameAt } from '@/pet/engine/sprite.ts'
import {
  cameraHalfWidth,
  modelTargetBox,
  rendererFor,
  selectAnimationClip,
  toViewport,
} from '@/pet/render/types.ts'
import { ringCrowdingWarning, ringSectors, sectorIndexAt } from '@/pet/ping/ringModel.ts'
import { maskSvgUrl, shouldMaskPets } from '@/pet/render/occlusion.ts'
import { defaultConfig } from '@/pet/config.ts'
import { createPingRuntime, type PingRuntimeDeps } from '@/pet/ping/usePingRuntime.ts'
import { PetAgentHost, type PetBindingsState } from '@/pet/agent/host.ts'
import type { PetAgentClient } from '@/pet/agent/client.ts'

describe('渲染器选择', () => {
  it('静态图、序列帧、图集都交给 Canvas 2D，模型交给 Three', () => {
    expect(rendererFor({ type: 'static', source: 'a.png' })).toBe('canvas2d')
    expect(rendererFor({ type: 'frames', sources: ['a.png'], fps: 8, loop: true })).toBe('canvas2d')
    expect(rendererFor({ type: 'spritesheet', source: 's.png', frameWidth: 8, frameHeight: 8, frameCount: 4, fps: 8, loop: true })).toBe('canvas2d')
    expect(rendererFor({ type: 'model', source: 'm.glb' })).toBe('three')
    // 资源缺失时回落到 2D，占位图不会把渲染层拖死。
    expect(rendererFor(undefined)).toBe('canvas2d')
  })

  it('模型帧不带裁剪，并标明来源类型', () => {
    const frame = frameAt({ type: 'model', source: 'cat.glb' }, 1234, { width: 200, height: 320 })
    expect(frame.type).toBe('model')
    expect(frame.source).toBe('cat.glb')
    expect(frame.sw).toBe(200)
    expect(frame.sh).toBe(320)
  })
})

describe('模型显示框', () => {
  const rect = { x: 100, y: 200, width: 160, height: 240 }

  it('默认铺满精灵框', () => {
    const box = modelTargetBox(rect, { type: 'model', source: 'm.glb' })
    expect(box).toEqual(rect)
  })

  it('model_scale 围绕中心缩放，offsetY 按框高比例下移', () => {
    const box = modelTargetBox(rect, { type: 'model', source: 'm.glb', modelScale: 0.5, offsetY: 0.25 })
    expect(box.width).toBe(80)
    expect(box.height).toBe(120)
    // 水平居中
    expect(box.x).toBe(100 + 40)
    // 0.5 缩放下贴底，再下移 0.25 × 240
    expect(box.y).toBeCloseTo(200 + 120 + 60, 5)
  })
})

describe('外部动画名映射', () => {
  const clips = ['Stand', 'WalkCycle', 'Jump_Up', 'Cheer']

  it('精确匹配优先', () => {
    expect(selectAnimationClip('walk', ['walk', 'idle'])).toEqual({ name: 'walk', match: 'exact' })
  })

  it('别名匹配外部命名，不要求遵守 Sunday 约定', () => {
    const selection = selectAnimationClip('idle', clips)
    expect(selection.match).toBe('alias')
    expect(selection.name).toBe('Stand')
    expect(selectAnimationClip('walk', clips).name).toBe('WalkCycle')
    expect(selectAnimationClip('dance', clips).name).toBe('Cheer')
  })

  it('pet.json 显式指定的片段名优先级最高', () => {
    const selection = selectAnimationClip('dance', clips, 'Jump_Up')
    expect(selection).toEqual({ name: 'Jump_Up', match: 'exact' })
  })

  it('都对不上时退回第一段，并标明是回退', () => {
    const selection = selectAnimationClip('climb', ['OnlyOne'])
    expect(selection).toEqual({ name: 'OnlyOne', match: 'fallback' })
  })

  it('模型里没有动画时明确返回 none，而不是猜', () => {
    expect(selectAnimationClip('idle', [])).toEqual({ name: null, match: 'none' })
  })
})

describe('视口换算', () => {
  const overlay = { x: 0, y: -1080, width: 1920, height: 2160 }

  it('把世界坐标矩形翻成 WebGL 左下原点视口', () => {
    // 虚拟桌面从 y=-1080 开始：世界 y=0 距离顶部 1080，距底部 1080。
    const viewport = toViewport({ x: 10, y: 0, width: 100, height: 200 }, overlay)
    expect(viewport.x).toBe(10)
    expect(viewport.y).toBe(2160 - (0 - -1080) - 200)
    expect(viewport.width).toBe(100)
    expect(viewport.height).toBe(200)
  })

  it('不可见尺寸不会产生 0 或负数视口', () => {
    const viewport = toViewport({ x: -50, y: -5000, width: 0, height: 0 }, overlay)
    expect(viewport.width).toBeGreaterThanOrEqual(1)
    expect(viewport.height).toBeGreaterThanOrEqual(1)
    expect(viewport.x).toBeGreaterThanOrEqual(0)
  })
})

describe('Ping 轮盘分层与扇区命中', () => {
  const sectors = [
    { id: 'q', label: '提问', icon: '?', kind: 'question' as const, color: '#1', enabled: true },
    { id: 'x', label: '注意', icon: '!', kind: 'exclamation' as const, color: '#2', enabled: true },
    { id: 'more', label: '更多', icon: '＋', kind: 'subring' as const, color: '#3', enabled: true, subring: 'extra' },
    { id: 's1', label: '子一', icon: '1', kind: 'custom' as const, color: '#4', enabled: true, group: 'extra', action: 'settings' },
    { id: 's2', label: '子二', icon: '2', kind: 'custom' as const, color: '#5', enabled: true, group: 'extra', action: 'import' },
    { id: 'off', label: '关掉', icon: '✕', kind: 'custom' as const, color: '#6', enabled: false, group: 'extra' },
  ]

  it('主轮盘只放没有 group 的启用项', () => {
    const ids = ringSectors(sectors, null).map(sector => sector.id)
    expect(ids).toEqual(['q', 'x', 'more'])
  })

  it('子轮盘按 subring 分组，包含启用项、排除禁用项', () => {
    const parent = sectors[2]
    const ids = ringSectors(sectors, parent).map(sector => sector.id)
    expect(ids).toEqual(['s1', 's2'])
  })

  it('扇区命中按角度等分，中心死区不选中', () => {
    // 4 个扇区、半径 100：上方（dy=-100）对应第 0 个。
    expect(sectorIndexAt(0, -100, 4, 100, 12)).toBe(0)
    expect(sectorIndexAt(100, 0, 4, 100, 12)).toBe(1)
    expect(sectorIndexAt(0, 100, 4, 100, 12)).toBe(2)
    expect(sectorIndexAt(-100, 0, 4, 100, 12)).toBe(3)
    // 中心与环外都不算命中。
    expect(sectorIndexAt(3, 3, 4, 100, 12)).toBe(-1)
    expect(sectorIndexAt(400, 0, 4, 100, 12)).toBe(-1)
  })

  it('扇区很多时给出可用性提示而不是静默截断', () => {
    expect(ringCrowdingWarning(6)).toBeNull()
    expect(ringCrowdingWarning(10)).toContain('建议调大环半径')
    expect(ringCrowdingWarning(20)).toContain('子轮盘')
  })
})

describe('局部遮挡遮罩', () => {
  const overlay = { x: -1920, y: 0, width: 1920, height: 1080 }

  it('窗口落在覆盖层里时挖出对应的洞', () => {
    const url = maskSvgUrl(overlay, [
      { x: -1800, y: 100, width: 600, height: 400 },
    ])
    expect(url.startsWith('data:image/svg+xml')).toBe(true)
    // 局部坐标 = 屏幕坐标 - 覆盖层原点：-1800 - (-1920) = 120
    expect(url).toContain('M120 100h600v400')
    expect(url).toContain('fill-rule')
  })

  it('没有相交窗口时不产生遮罩（避免整层被误盖）', () => {
    expect(maskSvgUrl(overlay, [{ x: 4000, y: 4000, width: 400, height: 300 }])).toBe('')
  })

  it('窗口部分越界时按交集裁剪', () => {
    const url = maskSvgUrl(overlay, [{ x: -2000, y: -50, width: 200, height: 200 }])
    // 交集从 (0,0) 到 (120,150)
    expect(url).toContain('M0 0h120v150')
  })

  it('整层被窗口覆盖时给出全黑遮罩', () => {
    const url = maskSvgUrl(overlay, [{ x: -3000, y: -500, width: 5000, height: 3000 }])
    expect(url).toContain("fill='%23000'")
  })

  it('只有 clip 模式才裁剪，其他模式不动宠物', () => {
    expect(shouldMaskPets('clip', 2)).toBe(true)
    expect(shouldMaskPets('clip', 0)).toBe(false)
    expect(shouldMaskPets('top', 3)).toBe(false)
    expect(shouldMaskPets('behind', 3)).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Ping 与桌宠是两个独立功能（用户决定："ping 环跟桌宠应当是解耦的，它们是两个
// 独立的功能，我只是在这一次设计方案中把它写在一起了"）。
// 这组测试钉住两件事：
//   1. 模块边界：ping/** 不 import 桌宠引擎（engine/*）与桌宠运行时（usePetRuntime），
//      Ping 组件也不再引用 usePetRuntime；
//   2. 零宠物可用：没有任何宠物实例时，轮盘、扇区命中、目标路由、卡片去重照常工作。
// ---------------------------------------------------------------------------
describe('Ping 解耦与零宠物可用', () => {
  const petRoot = resolve(import.meta.dirname, '../src/pet')

  function sourceOf(relative: string): string {
    return readFileSync(resolve(petRoot, relative), 'utf8')
  }

  it('ping 模块不依赖桌宠引擎与桌宠运行时', () => {
    const files = readdirSync(resolve(petRoot, 'ping')).filter(name => name.endsWith('.ts'))
    expect(files.length).toBeGreaterThanOrEqual(2)
    for (const name of files) {
      const source = sourceOf(`ping/${name}`)
      expect(source, `${name} 不得 import 桌宠引擎`).not.toMatch(/from\s+['"][^'"]*engine\//)
      expect(source, `${name} 不得 import 桌宠运行时`).not.toMatch(/from\s+['"][^'"]*usePetRuntime/)
    }
  })

  it('Ping 组件只依赖 Ping 运行时，不再引用 usePetRuntime', () => {
    for (const name of ['PingRing.vue', 'PingMarkerFx.vue', 'SessionCard.vue', 'PingCardWindow.vue']) {
      const source = sourceOf(`ui/${name}`)
      expect(source, `${name} 不得引用桌宠运行时`).not.toContain('usePetRuntime')
      expect(source, `${name} 应改为接收 ping 运行时`).toContain('PingRuntime')
    }
    // 截图窗口是独立文档：它只依赖 Agent 宿主，不引用桌宠运行时或 Ping 运行时。
    for (const name of ['CaptureEditor.vue', 'CaptureApp.vue']) {
      const source = sourceOf(`ui/${name}`)
      expect(source, `${name} 不得引用桌宠运行时`).not.toContain('usePetRuntime')
    }
    // 组合点保留在桌宠运行时里：由它创建 Ping 并注入共享能力。
    expect(sourceOf('ui/usePetRuntime.ts')).toContain("from '../ping/usePingRuntime.ts'")
  })

  it('Ping 主环用图标而不是文字，完整名称留在 title 里', () => {
    const ring = sourceOf('ui/PingRing.vue')
    for (const icon of [
      'MessageCircleQuestionMark',
      'NotebookPen',
      'TriangleAlert',
      'SquareDashed',
      'MessagesSquare',
      'ArrowLeftRight',
    ]) {
      expect(ring, `主环缺少 ${icon} 图标`).toContain(icon)
    }
    expect(ring).toContain('sectorIcon')
    const rootItems = ring.slice(ring.indexOf('主轮盘：只有图标'), ring.indexOf('</svg>'))
    expect(rootItems).toContain('<title>')
    // 主环扇区不再画单字/标签；二三级项目/会话仍然保持文字。
    expect(rootItems).not.toContain('<text')
  })

  function makeDeps(overrides: Partial<PingRuntimeDeps> = {}): PingRuntimeDeps {
    return {
      config: defaultConfig(),
      overlay: { x: 0, y: 0, width: 1920, height: 1080, scale: 1 },
      monitors: () => [{ id: 'm1', x: 0, y: 0, width: 1920, height: 1080, primary: true, scale: 1 }],
      cursor: { x: 960, y: 540 },
      getHost: () => null,
      getClient: () => null,
      save: () => {},
      report: () => {},
      notify: () => {},
      openSessionPicker: () => {},
      customActions: {},
      ...overrides,
    }
  }

  it('零宠物时轮盘照常打开：扇区来自配置、悬停按角度命中', () => {
    const ping = createPingRuntime(makeDeps())
    expect(ping.ring.visible).toBe(false)
    ping.openRing(960, 540)
    expect(ping.ring.visible).toBe(true)
    // 默认 6 个启用扇区，全部来自 config.ping.sectors，数量不硬编码。
    // user:“把“切换会话”放在最右边”+(切换会话固定在正右方扇区，其余保持相对顺序)。
    expect(ping.ring.sectors.map(sector => sector.id)).toEqual([
      'question', 'switch', 'exclamation', 'note', 'select', 'chat',
    ])
    // 正上方 100px：第 0 个扇区（提问），不依赖任何宠物实例。
    ping.onCursorMoved(960, 540 - 100)
    expect(ping.ring.hovered).toBe('question')
  })

  it('零宠物时按中心死区取消、松开执行走完整提交路径', async () => {
    const reported: string[] = []
    const ping = createPingRuntime(makeDeps({ report: scope => { reported.push(scope) } }))
    // 中心死区：取消，不产生标记。
    ping.openRing(960, 540)
    await ping.commitRing(960, 540)
    expect(ping.ring.visible).toBe(false)
    expect(ping.markerFx.visible).toBe(false)
    // 上方命中「提问」：先标记（视觉确认），截图在无 Tauri 环境如实失败不伪造。
    ping.openRing(960, 540)
    await ping.commitRing(960, 540 - 100)
    expect(ping.markerFx.visible).toBe(true)
    expect(ping.capture.busy).toBe(false)
    expect(ping.capture.lastError).not.toBe('')
    expect(ping.ring.visible).toBe(false)
    expect(reported.some(scope => scope.startsWith('ping:'))).toBe(true)
  })

  it('Ping 目标：显式 → My Project 的默认 ping 会话；插件会话被丢弃', async () => {
    const client = {
      ensurePingSession: async () => ({ projectId: 'proj-ping', sessionId: 'sess-ping', created: true }),
    } as unknown as PetAgentClient
    // 显式目标：完全不碰 client。
    const explicit = new PetAgentHost(client, {
      pets: {},
      ping: { projectId: 'proj-1', sessionId: 'sess-1' },
    } as PetBindingsState)
    const target1 = await explicit.pingTarget()
    expect(target1).toMatchObject({ projectId: 'proj-1', sessionId: 'sess-1', source: 'explicit' })
    // user:“默认会话的名字就叫“ping””+(插件会话不能当目标：历史配置里的
    // workflow 目标会被丢弃，回到 My Project 的默认 ping 会话。)
    const stale = new PetAgentHost(client, {
      pets: {},
      ping: { projectId: 'proj-1', sessionId: 'workflow:abc' },
    } as PetBindingsState)
    const target2 = await stale.pingTarget()
    expect(target2).toMatchObject({ projectId: 'proj-ping', sessionId: 'sess-ping', source: 'fallback' })
    expect(stale.bindings.ping).toEqual({ projectId: 'proj-ping', sessionId: 'sess-ping' })
    // 桌宠绑定与 Ping 目标无关（不再借用）。
    const withPet = new PetAgentHost(client, {
      pets: { 'pet-a': { projectId: 'proj-p', sessionId: 'sess-p' } },
      ping: { projectId: null, sessionId: null },
    } as unknown as PetBindingsState)
    const target3 = await withPet.pingTarget()
    expect(target3).toMatchObject({ projectId: 'proj-ping', sessionId: 'sess-ping', source: 'fallback' })
  })

  it('同一会话多条 Ping 进同一张卡片（去重），切换目标只改路由', () => {
    const saved: unknown[] = []
    const config = defaultConfig()
    const ping = createPingRuntime(makeDeps({
      config,
      save: () => { saved.push(config.ping.target) },
    }))
    const first = ping.ensureCard('proj-1', 'sess-1')
    const again = ping.ensureCard('proj-1', 'sess-1')
    // reactive Map 取出的同一会话卡片是同一个对象（去重）。
    expect(again).toBe(ping.cards.get('sess-1'))
    expect(again).toEqual(first)
    expect(ping.cards.size).toBe(1)
    expect(ping.ensureCard(null, 'sess-2')).toEqual(ping.cards.get('sess-2'))
    expect(ping.ensureCard(null, 'sess-2')).toBe(ping.cards.get('sess-2'))
    expect(ping.cards.size).toBe(2)
    // 轮盘内「切换会话」：写回 host 路由 + 配置持久化。
    // user:“ping完之后用一个合适的大小打开Sunday本体”+(切换目标不再开卡片窗口。)
    const host = new PetAgentHost({} as PetAgentClient, { pets: {}, ping: { projectId: null, sessionId: null } })
    const depsPing = createPingRuntime(makeDeps({
      config,
      save: () => { saved.push(config.ping.target) },
      getHost: () => host,
      getClient: () => ({ listSessions: async () => [] } as unknown as PetAgentClient),
    }))
    depsPing.applyPickedTarget('proj-9', 'sess-9')
    expect(config.ping.target).toEqual({ projectId: 'proj-9', sessionId: 'sess-9' })
    expect(host.bindings.ping).toEqual({ projectId: 'proj-9', sessionId: 'sess-9' })
    expect(depsPing.cards.has('sess-9')).toBe(false)
    expect(saved.length).toBeGreaterThan(0)
  })

  it('自定义扇区动作未注入时只报错，不静默吞掉', async () => {
    const reported: { scope: string; message: string }[] = []
    const ping = createPingRuntime(makeDeps({
      report: (scope, error) => { reported.push({ scope, message: String((error as Error).message) }) },
    }))
    await ping.executeSector(
      { id: 'c1', label: '刷新地形', icon: 'r', kind: 'custom', color: '#fff', enabled: true, action: 'refresh-l3' },
      { x: 0, y: 0 },
    )
    expect(reported).toEqual([])
    // 注入后的动作会被调用（解耦：动作由组合方提供，Ping 只负责分派）。
    let toggled = 0
    const wired = createPingRuntime(makeDeps({
      customActions: { toggleTerrainLines: () => { toggled += 1 } },
    }))
    await wired.executeSector(
      { id: 'c2', label: '地形线', icon: 't', kind: 'custom', color: '#fff', enabled: true, action: 'debug-terrain' },
      { x: 0, y: 0 },
    )
    expect(toggled).toBe(1)
    // 未绑定动作：报「未绑定」而不是无响应。
    await ping.executeSector(
      { id: 'c3', label: '神秘项', icon: '?', kind: 'custom', color: '#fff', enabled: true, action: 'no-such-action' },
      { x: 0, y: 0 },
    )
    expect(reported[0]?.message).toContain('神秘项')
  })
})

describe('3D 相机取景', () => {
  // user:"出现了，但是没有下半身"+"渲染器只负责正确表现角色"+
  // user:"碰撞箱不对，比实际偏高"+
  // (竖直可见区间固定 [0,1.05]（半高 0.525）：脚底贴精灵框底边，和物理 AABB
  //  的脚底同一锚点；头顶留 5% 余量。水平半宽必须与竖直同比例，否则"全身入画"
  //  修复会带来固定 ~10% 的横向拉伸；窄框保底可见宽 0.5，
  //  0.5 世界单位宽的方块人在任何精灵框下都不被左右裁掉。)
  it('水平半宽与竖直半高（0.525）同比例，不产生横向拉伸', () => {
    for (const [width, height] of [[92, 158], [128, 160], [200, 200], [320, 180]]) {
      const aspect = width / height
      // 无拉伸 ⇔ 可见世界宽/可见世界高 == 像素宽/像素高 ⇔ 半宽/0.525 == aspect
      expect(cameraHalfWidth(aspect)).toBeCloseTo(0.525 * aspect, 12)
    }
  })

  it('方块人预设视口（92×158）下 0.5 宽的角色完整入画', () => {
    const halfWidth = cameraHalfWidth(92 / 158)
    expect(halfWidth).toBeGreaterThanOrEqual(0.25) // 可见宽 ≥ 0.5
    expect(0.25).toBeLessThanOrEqual(halfWidth) // 角色半宽 0.25 ≤ 可见半宽
  })

  it('极窄精灵框保底可见宽 0.5，不左右裁掉方块人', () => {
    expect(cameraHalfWidth(0.1)).toBe(0.25)
    expect(cameraHalfWidth(0)).toBe(0.25)
  })
})
