/**
 * 角色资源适配层：动画片段、帧推进与交互 Hitbox。
 *
 * user:“同一角色支持不同 Action 引用不同动画来源/格式，兼容则正常播放”+
 * (每个动作各自绑定一份资源；缺资源时回退到基础/静态姿态，物理照常运行。
 *  适配器只描述"怎么取一帧"，不认识物理、Action 或 UI。)
 */

export type ClipKind = 'static' | 'frames' | 'spritesheet' | 'model' | 'blocky'

export interface StaticClip {
  type: 'static'
  source: string
}

export interface FramesClip {
  type: 'frames'
  /** 按顺序播放的帧图，相对角色包根目录。 */
  sources: string[]
  fps: number
  loop: boolean
}

export interface SpritesheetClip {
  type: 'spritesheet'
  source: string
  frameWidth: number
  frameHeight: number
  frameCount: number
  fps: number
  loop: boolean
  columns?: number
  /** 帧范围（含首尾），用于一张图集里只取一段。 */
  startFrame?: number
  endFrame?: number
}

/**
 * 3D 模型片段（glTF/GLB）。渲染交给 Three.js 适配器，物理与 Action 完全不知道它的存在。
 * `clip` 是 glTF 里的 animation 名；缺省用文件里的第一段动画。
 */
export interface ModelClip {
  type: 'model'
  source: string
  clip?: string
  loop?: boolean
  /** 模型朝向修正（弧度），用于把模型"正面"转到朝向相机。 */
  rotationY?: number
  /** 在自动归一到精灵框高度之外再乘一个系数。 */
  modelScale?: number
  /** 相对精灵框的竖直偏移，单位为框高的比例（正数向下）。 */
  offsetY?: number
}

/**
 * 方块人：不依赖外部模型文件，由渲染层按 Minecraft 皮肤布局现场搭盒式骨架。
 * 皮肤可以是角色包里的 PNG，也可以是内置生成的默认皮肤。
 */
export interface BlockyClip {
  type: 'blocky'
  /** 皮肤图片（相对角色包根）；缺省时用内置皮肤。 */
  skin?: string
  model?: 'steve' | 'alex'
}

export type PetClip = StaticClip | FramesClip | SpritesheetClip | ModelClip | BlockyClip

export type AnimationMap = Record<string, PetClip | undefined>

export interface FrameRef {
  /** 这个帧属于哪类资源：model 由 3D 层渲染，其余由 Canvas 2D 绘制。 */
  type: ClipKind
  /** 帧在资源里的索引。 */
  index: number
  /** 图片地址（帧图或图集）。 */
  source: string
  /** 在该图片上的裁剪矩形，图集需要，序列帧/静态图为整图。 */
  sx: number
  sy: number
  sw: number
  sh: number
}

export interface ClipGeometry {
  width: number
  height: number
}

/**
 * 取某一时刻的帧。纯函数，可单测：
 * - 静态图永远第 0 帧；
 * - 序列帧/图集按 fps 推进；
 * - 非循环片段停在最后一帧（**不靠动画时长决定物理**）。
 */
export function frameAt(
  clip: PetClip,
  elapsedMs: number,
  geometry: ClipGeometry,
): FrameRef {
  if (clip.type === 'static') {
    return { type: 'static', index: 0, source: clip.source, sx: 0, sy: 0, sw: geometry.width, sh: geometry.height }
  }
  if (clip.type === 'model') {
    // 3D 模型没有"帧"，但渲染状态仍需要来源标识；绘制由 Three 层接管。
    return { type: 'model', index: 0, source: clip.source, sx: 0, sy: 0, sw: geometry.width, sh: geometry.height }
  }
  if (clip.type === 'blocky') {
    return { type: 'blocky', index: 0, source: clip.skin || '', sx: 0, sy: 0, sw: geometry.width, sh: geometry.height }
  }
  if (clip.type === 'frames') {
    // 老配置/pet.json 可能写 `frames` 而不是内部字段 `sources`（配置层会归一化，
    // 这里再兜一次：缺帧数组时不能每帧抛错，否则整个渲染循环停摆、桌宠消失）。
    const sources = Array.isArray(clip.sources) ? clip.sources : []
    if (sources.length === 0) {
      return { type: 'frames', index: 0, source: '', sx: 0, sy: 0, sw: geometry.width, sh: geometry.height }
    }
    const count = sources.length
    const raw = Math.floor((elapsedMs / 1000) * clip.fps)
    const index = clip.loop ? raw % count : Math.min(count - 1, raw)
    return { type: 'frames', index, source: sources[index], sx: 0, sy: 0, sw: geometry.width, sh: geometry.height }
  }
  const first = clip.startFrame ?? 0
  const last = clip.endFrame ?? clip.frameCount - 1
  const count = Math.max(1, last - first + 1)
  const raw = Math.floor((elapsedMs / 1000) * clip.fps)
  const local = clip.loop ? raw % count : Math.min(count - 1, raw)
  const index = first + local
  const columns = clip.columns ?? Math.max(1, Math.floor(geometry.width / Math.max(1, clip.frameWidth)))
  const column = index % columns
  const row = Math.floor(index / columns)
  return {
    type: 'spritesheet',
    index,
    source: clip.source,
    sx: column * clip.frameWidth,
    sy: row * clip.frameHeight,
    sw: clip.frameWidth,
    sh: clip.frameHeight,
  }
}

/** 资源里"用来预览/展示"的主文件；方块人返回皮肤（可能为空）。 */
export function clipPrimarySource(clip: PetClip | undefined): string {
  if (!clip) return ''
  if (clip.type === 'frames') return Array.isArray(clip.sources) ? clip.sources[0] || '' : ''
  if (clip.type === 'blocky') return clip.skin || ''
  return clip.source
}

export function clipDurationMs(clip: PetClip): number | null {
  if (clip.type === 'static') return 0
  if (clip.type === 'model') return null
  if (clip.type === 'blocky') return null
  if (clip.loop) return null
  if (clip.type === 'frames') return ((Array.isArray(clip.sources) ? clip.sources.length : 0) / Math.max(1, clip.fps)) * 1000
  const first = clip.startFrame ?? 0
  const last = clip.endFrame ?? clip.frameCount - 1
  return ((last - first + 1) / Math.max(1, clip.fps)) * 1000
}

/**
 * 交互 Hitbox：归一化坐标（0..1，相对精灵边框）。
 * 与物理碰撞体是两个东西——改这里不会影响地形碰撞。
 */
export interface PetHitbox {
  id: string
  name: string
  x: number
  y: number
  width: number
  height: number
  /** 单击执行的 Action。 */
  action: string
  /** 双击执行的 Action（可选）。 */
  doubleAction?: string
  enabled: boolean
}

export function defaultHitboxes(): PetHitbox[] {
  return [
    {
      id: 'body',
      name: '身体',
      x: 0.08,
      y: 0.08,
      width: 0.84,
      height: 0.84,
      action: 'interact',
      doubleAction: 'jump_happy',
      enabled: true,
    },
  ]
}

/** 本地坐标（精灵像素）命中测试，按朝向镜像。 */
export function hitTest(
  hitboxes: PetHitbox[],
  localX: number,
  localY: number,
  spriteWidth: number,
  spriteHeight: number,
  facing: 1 | -1,
): PetHitbox | null {
  const normalizedX = localX / Math.max(1, spriteWidth)
  const normalizedY = localY / Math.max(1, spriteHeight)
  const mirrored = facing < 0 ? 1 - normalizedX : normalizedX
  // 后声明的区域优先：头/尾巴这类小区域通常写在身体区域之后，
  // 否则点头部永远只会命中"身体"。
  for (let index = hitboxes.length - 1; index >= 0; index -= 1) {
    const hitbox = hitboxes[index]
    if (!hitbox.enabled) continue
    if (mirrored >= hitbox.x && mirrored <= hitbox.x + hitbox.width
      && normalizedY >= hitbox.y && normalizedY <= hitbox.y + hitbox.height) {
      return hitbox
    }
  }
  return null
}

/**
 * 交互 Hitbox 的世界矩形。
 *
 * user:"碰撞箱不对，比实际偏高"+
 * (绘制、点击、穿透必须用同一个矩形：Hitbox 的归一化坐标相对精灵框，
 *  朝向镜像也只在这里做一次，避免"画出来的框"和"能点到的框"各算各的。)
 */
export function hitboxWorldRect(
  hitbox: PetHitbox,
  rect: { x: number; y: number; width: number; height: number },
  facing: 1 | -1,
): { x: number; y: number; width: number; height: number } {
  const offsetX = facing < 0 ? 1 - hitbox.x - hitbox.width : hitbox.x
  return {
    x: rect.x + offsetX * rect.width,
    y: rect.y + hitbox.y * rect.height,
    width: hitbox.width * rect.width,
    height: hitbox.height * rect.height,
  }
}

/** 角色当前可见的整体矩形（物理位置 + 精灵尺寸 + 缩放）。 */
export function spriteRect(
  position: { x: number; y: number },
  spriteWidth: number,
  spriteHeight: number,
  scale: number,
): { x: number; y: number; width: number; height: number } {
  const width = spriteWidth * scale
  const height = spriteHeight * scale
  // 判定框脚底中心对齐精灵框水平中心，精灵底边对齐脚底（泰拉瑞亚式）。
  return {
    x: position.x - width / 2,
    y: position.y - height,
    width,
    height,
  }
}
