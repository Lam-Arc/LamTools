/**
 * 方块人的纯逻辑：Minecraft 皮肤布局、盒面 UV、动作姿态。
 *
 * 这里不碰 Three.js，也不碰 DOM：UV 表算错或姿态抖动都能在单测里立刻发现，
 * 不用等到真机看见角色扭曲。
 *
 * 皮肤布局遵循 Minecraft 64×64 标准网格（Steve / Alex 同一套）：
 * - 头 8×8×8 在 (0,0)
 * - 身体 8×12×4 在 (16,16)
 * - 右臂 4×12×4 在 (40,16)，左臂在 (32,48)
 * - 右腿 4×12×4 在 (0,16)，左腿在 (16,48)
 */

export type BlockyModel = 'steve' | 'alex'

export interface SkinBox {
  /** 图集左上角。 */
  x: number
  y: number
  /** 盒尺寸（像素/模型单位）。 */
  w: number
  h: number
  d: number
}

/** 标准皮肤网格。Alex 的手臂更细，但 UV 起点相同。 */
export function skinBoxes(model: BlockyModel): {
  head: SkinBox
  body: SkinBox
  armRight: SkinBox
  armLeft: SkinBox
  legRight: SkinBox
  legLeft: SkinBox
} {
  const armWidth = model === 'alex' ? 3 : 4
  return {
    head: { x: 0, y: 0, w: 8, h: 8, d: 8 },
    body: { x: 16, y: 16, w: 8, h: 12, d: 4 },
    armRight: { x: 40, y: 16, w: armWidth, h: 12, d: 4 },
    armLeft: { x: 32, y: 48, w: armWidth, h: 12, d: 4 },
    legRight: { x: 0, y: 16, w: 4, h: 12, d: 4 },
    legLeft: { x: 16, y: 48, w: 4, h: 12, d: 4 },
  }
}

export interface UvRect {
  u0: number
  v0: number
  u1: number
  v1: number
}

export interface FaceUv {
  /** BoxGeometry 的面顺序：+X, -X, +Y, -Y, +Z, -Z。 */
  order: ('right' | 'left' | 'top' | 'bottom' | 'front' | 'back')[]
  rects: UvRect[]
}

/**
 * 把一个盒子的展开图映射到六个面。
 *
 * Minecraft 的展开顺序是 [顶][底][右][前][左][后] 横向排布，
 * 而 BoxGeometry 的顶点顺序是 +X,-X,+Y,-Y,+Z,-Z，必须显式对应，
 * 否则贴图会错位成"前后颠倒"。
 */
export function boxFaceUvs(box: SkinBox, textureWidth = 64, textureHeight = 64): FaceUv {
  const { x, y, w, h, d } = box
  const toRect = (px: number, py: number, pw: number, ph: number): UvRect => ({
    // three 的 UV 原点在左下，所以 v 要翻转。
    u0: px / textureWidth,
    u1: (px + pw) / textureWidth,
    v0: 1 - (py + ph) / textureHeight,
    v1: 1 - py / textureHeight,
  })
  return {
    order: ['right', 'left', 'top', 'bottom', 'front', 'back'],
    rects: [
      // user:"你没有发现你的面向方向左右搞反了吗"+
      // (方块的 +X 是角色左侧：骨架把右臂放在 -X、左臂放在 +X。展开图的
      //  "左/右"是角色自身的左右，必须对应到 -X/+X，否则侧脸与皮肤左右镜像。)
      toRect(x + d + w, y + d, d, h), // +X：角色左侧
      toRect(x, y + d, d, h), // -X：角色右侧
      toRect(x + d, y, w, d), // +Y 顶
      toRect(x + d + w, y, w, d), // -Y 底
      toRect(x + d, y + d, w, h), // +Z 前
      toRect(x + d + w + d, y + d, w, h), // -Z 后
    ],
  }
}

export interface BlockyPose {
  head: { x: number; y: number; z: number }
  body: { x: number; y: number; z: number }
  armLeft: { x: number; y: number; z: number }
  armRight: { x: number; y: number; z: number }
  legLeft: { x: number; y: number; z: number }
  legRight: { x: number; y: number; z: number }
  /** 整体上下偏移，单位是模型单位（1 = 一个像素）。 */
  bob: number
}

function pose(
  overrides: Partial<{
    head: [number, number, number]
    body: [number, number, number]
    armLeft: [number, number, number]
    armRight: [number, number, number]
    legLeft: [number, number, number]
    legRight: [number, number, number]
    bob: number
  }> = {},
): BlockyPose {
  const v = (tuple: [number, number, number] | undefined) => ({
    x: tuple?.[0] ?? 0,
    y: tuple?.[1] ?? 0,
    z: tuple?.[2] ?? 0,
  })
  return {
    head: v(overrides.head),
    body: v(overrides.body),
    armLeft: v(overrides.armLeft),
    armRight: v(overrides.armRight),
    legLeft: v(overrides.legLeft),
    legRight: v(overrides.legRight),
    bob: overrides.bob ?? 0,
  }
}

const TAU = Math.PI * 2

/**
 * 动作 → 姿态。全部是程序化贴图无关的骨骼角度，
 * 因此换皮肤、换模型宽度都不影响动作表现。
 */
export function blockyPose(actionId: string, elapsedMs: number): BlockyPose {
  // user:"同时不要给走路动画开倍速，我从来没有说过有这一项吧"+
  // (动作按固定节奏播放，不按移动速度倍速；设计没写的东西不加。)
  const t = elapsedMs / 1000
  const phase = t * 2 * TAU
  const swing = Math.sin(phase)
  const swing2 = Math.sin(phase + Math.PI)
  switch (actionId) {
    case 'walk':
      return pose({
        armLeft: [swing * 0.55, 0, 0],
        armRight: [swing2 * 0.55, 0, 0],
        legLeft: [swing2 * 0.6, 0, 0],
        legRight: [swing * 0.6, 0, 0],
        head: [0, Math.sin(phase * 0.5) * 0.08, 0],
        bob: Math.abs(Math.sin(phase)) * 0.6,
      })
    case 'jump':
    case 'jump_happy':
      return pose({
        armLeft: [-2.2, 0, -0.25],
        armRight: [-2.2, 0, 0.25],
        legLeft: [0.35, 0, 0],
        legRight: [-0.2, 0, 0],
        head: [-0.12, 0, 0],
        bob: 0.5,
      })
    case 'fall':
      return pose({
        armLeft: [-1.4, 0, -0.6],
        armRight: [-1.4, 0, 0.6],
        legLeft: [0.45, 0, 0.12],
        legRight: [-0.3, 0, -0.12],
        head: [0.1, 0, 0],
      })
    case 'climb':
      return pose({
        armLeft: [Math.PI + swing * 0.35, 0, -0.1],
        armRight: [Math.PI + swing2 * 0.35, 0, 0.1],
        legLeft: [swing2 * 0.5, 0, 0],
        legRight: [swing * 0.5, 0, 0],
        head: [-0.2, 0, 0],
      })
    case 'hang':
      return pose({
        armLeft: [Math.PI, 0, -0.05],
        armRight: [Math.PI, 0, 0.05],
        legLeft: [0.12, 0, 0],
        legRight: [-0.12, 0, 0],
        head: [-0.15, 0, 0],
        bob: -0.3,
      })
    case 'question':
      // user:"或者你加一个疑问动作"+
      // user:"提问的时候，手和脑袋叠到一块儿了，把手往外打开一点"+
      // (举手 + 歪头 + 轻微起伏；手臂向外摆开，手不贴脸。)
      return pose({
        armLeft: [0.15, 0, -0.12],
        armRight: [-2.15, 0, -0.28],
        legLeft: [0.05, 0, 0.05],
        legRight: [-0.05, 0, -0.05],
        head: [0.04, 0, 0.12],
        bob: 0.2 + Math.sin(t * 2.2) * 0.25,
      })
    case 'rest': {
      // user:"而且休息的时候为什么没有腿"+
      // (原来腿绕 +X 转 90°，是往身后折的，正面/侧面都被身体挡住；改成
      //  向前伸并略微外分，身体坐到低处，正面能看见两条腿。)
      const breath = Math.sin(t * 1.4) * 0.12
      return pose({
        armLeft: [0.5, 0, 0.2],
        armRight: [0.5, 0, -0.2],
        legLeft: [-1.15, 0, 0.4],
        legRight: [-1.15, 0, -0.4],
        head: [0.16, 0, 0],
        bob: -6.2 + breath,
      })
    }
    case 'dance': {
      const bounce = Math.abs(Math.sin(t * 6))
      return pose({
        armLeft: [-2.4 + Math.sin(t * 6) * 0.4, 0, -0.5],
        armRight: [-2.4 + Math.cos(t * 6) * 0.4, 0, 0.5],
        legLeft: [Math.sin(t * 6) * 0.25, 0, 0.06],
        legRight: [-Math.sin(t * 6) * 0.25, 0, -0.06],
        head: [0, Math.sin(t * 3) * 0.3, 0],
        bob: bounce * 1.2,
      })
    }
    case 'interact':
    case 'interact_head':
      return pose({
        armLeft: [-0.4, 0, -0.25],
        armRight: [-1.9 + Math.sin(t * 9) * 0.35, 0, 0.2],
        head: [-0.06, 0, 0.04],
        bob: 0.2,
      })
    default:
      // 待机：轻微呼吸与手臂摆动，别做成完全静止的木桩。
      return pose({
        armLeft: [Math.sin(t * 1.6) * 0.06, 0, -0.04],
        armRight: [Math.sin(t * 1.6 + 0.6) * 0.06, 0, 0.04],
        head: [Math.sin(t * 0.9) * 0.05, Math.sin(t * 0.6) * 0.12, 0],
        bob: Math.sin(t * 1.6) * 0.18,
      })
  }
}

/**
 * 内置默认皮肤的参数：不依赖任何二进制资源，启动时按这张表画出来。
 * 颜色取自经典方块人配色，深浅按面区分，避免纯色看起来像纸片。
 */
export interface SkinPaint {
  /** 展开图左上角。 */
  box: SkinBox
  face: string
  side: string
  top: string
  bottom: string
}

export function defaultSkinPaint(model: BlockyModel = 'steve'): SkinPaint[] {
  const boxes = skinBoxes(model)
  return [
    { box: boxes.head, face: '#c69a76', side: '#b1845f', top: '#5a4433', bottom: '#8f6a4c' },
    { box: boxes.body, face: '#3b9ecb', side: '#3189b0', top: '#4bb4e0', bottom: '#275d78' },
    { box: boxes.armRight, face: '#c69a76', side: '#b1845f', top: '#3b9ecb', bottom: '#b1845f' },
    { box: boxes.armLeft, face: '#c69a76', side: '#b1845f', top: '#3b9ecb', bottom: '#b1845f' },
    { box: boxes.legRight, face: '#3b4f9c', side: '#32428a', top: '#2a3566', bottom: '#232d58' },
    { box: boxes.legLeft, face: '#3b4f9c', side: '#32428a', top: '#2a3566', bottom: '#232d58' },
  ]
}
