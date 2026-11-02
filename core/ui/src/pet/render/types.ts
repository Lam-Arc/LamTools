/**
 * 渲染适配层的公共契约。
 *
 * user:“优先实现统一渲染适配接口，保留现有物理与 Action 内核；角色的世界位置和速度
 * 由现有物理系统控制，渲染器只负责正确表现角色和动画”+
 * (Canvas 2D 与 Three.js 都只是"表现层"，谁也拿不到位置控制权。)
 */
import type { PetClip } from '../engine/sprite.ts'

export type RendererKind = 'canvas2d' | 'three'

export interface RenderablePet {
  id: string
  /** 当前动作对应的资源；缺失时上层已经做了回退。 */
  clip: PetClip | undefined
  rect: { x: number; y: number; width: number; height: number }
  facing: 1 | -1
  actionId: string
  /** 当前动作已播放时长，2D 靠它取帧，3D 靠它推 mixer。 */
  elapsedMs: number
  visible: boolean
  packId: string | null
  /** 水平速度，用于让走路动作跟着真实速度加快。 */
}

/** 一个资源该由谁来画。未知类型一律回落到 2D 占位，不让渲染失败拖垮物理。 */
export function rendererFor(clip: PetClip | undefined): RendererKind {
  // 3D 模型与方块人都由 WebGL 层绘制；方块人不加载任何外部模型文件。
  return clip?.type === 'model' || clip?.type === 'blocky' ? 'three' : 'canvas2d'
}

/** 3D 模型的显示框：在精灵框高度内归一，允许 clip 再叠加缩放与竖直偏移。 */
export function modelTargetBox(
  rect: { x: number; y: number; width: number; height: number },
  clip: PetClip | undefined,
): { x: number; y: number; width: number; height: number } {
  const scale = clip?.type === 'model' ? clip.modelScale ?? 1 : 1
  const offsetY = clip?.type === 'model' ? clip.offsetY ?? 0 : 0
  const height = rect.height * scale
  const width = rect.width * scale
  return {
    x: rect.x + (rect.width - width) / 2,
    y: rect.y + (rect.height - height) + offsetY * rect.height,
    width,
    height,
  }
}

/**
 * 外部动画名不必遵守 Sunday 命名：先精确匹配动作 id，再用别名表模糊匹配，
 * 最后退到文件里的第一段动画（并由调用方在诊断里说明用了回退）。
 */
const ACTION_ALIASES: Record<string, string[]> = {
  idle: ['idle', 'stand', 'wait', 'breath'],
  walk: ['walk', 'run', 'move'],
  jump: ['jump', 'hop'],
  jump_happy: ['jump_happy', 'happyjump', 'joy'],
  climb: ['climb'],
  hang: ['hang', 'dangle'],
  fall: ['fall', 'drop'],
  dance: ['dance', 'dancing', 'celebrate', 'cheer'],
  interact: ['interact', 'touch', 'wave'],
  rest: ['rest', 'sleep', 'sit'],
}

export interface ClipSelection {
  name: string | null
  /** 用的是精确匹配、别名匹配，还是退回第一段。 */
  match: 'exact' | 'alias' | 'fallback' | 'none'
}

export function selectAnimationClip(
  actionId: string,
  clipNames: readonly string[],
  preferred?: string,
): ClipSelection {
  if (clipNames.length === 0) return { name: null, match: 'none' }
  const wanted = (preferred || actionId).toLowerCase()
  const exact = clipNames.find(name => name.toLowerCase() === wanted)
  if (exact) return { name: exact, match: 'exact' }
  const aliases = ACTION_ALIASES[actionId] || []
  for (const alias of aliases) {
    const hit = clipNames.find(name => name.toLowerCase() === alias)
    if (hit) return { name: hit, match: 'alias' }
  }
  for (const alias of aliases) {
    const hit = clipNames.find(name => name.toLowerCase().includes(alias))
    if (hit) return { name: hit, match: 'alias' }
  }
  return { name: clipNames[0], match: 'fallback' }
}

/** 把世界坐标的矩形换算到 WebGL 视口（原点左下）。 */
export function toViewport(
  rect: { x: number; y: number; width: number; height: number },
  overlay: { x: number; y: number; width: number; height: number },
): { x: number; y: number; width: number; height: number } {
  const x = rect.x - overlay.x
  const y = overlay.height - (rect.y - overlay.y) - rect.height
  return {
    x: Math.max(0, Math.round(x)),
    y: Math.max(0, Math.round(y)),
    width: Math.max(1, Math.round(rect.width)),
    height: Math.max(1, Math.round(rect.height)),
  }
}

/**
 * 正交相机的水平半宽（世界单位）。
 *
 * user:"出现了，但是没有下半身"+"渲染器只负责正确表现角色"+
 * "碰撞箱不对，比实际偏高"+
 * (竖直可见区间固定为 [0, 1.05]：脚底贴精灵框底边（与物理 AABB 的脚底同一锚点），
 *  头顶留 5% 余量给动画；不再上下对称留白，否则角色会整体悬空在判定框底边之上。
 *  水平半宽必须与竖直同比例（0.525×aspect），否则角色被固定横向拉伸；
 *  同时保底 0.25（可见宽 0.5）：很窄的精灵框也不裁掉 0.5 世界单位宽的方块人。)
 */
export function cameraHalfWidth(aspect: number): number {
  return Math.max(0.25, 0.525 * aspect)
}
