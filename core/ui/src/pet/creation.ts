/**
 * 从用户选择的图片生成可发布桌宠（纯函数）。
 *
 * user:“普通用户无需写 JSON、准备压缩包、安装 Blender，即能用一张图片创建
 * 可运行桌宠；上传多张图即可定义动作”+
 * (把文件校验、动作推断、manifest 生成与资源条目整理从 UI 里抽出来，
 *  这样创建流程可以单测；真正写盘仍走 Rust 的原子角色包写入。)
 */
import {
  analyzeImport,
  MAX_ASSET_BYTES,
  MAX_IMAGE_EDGE,
  MAX_SCAN_BYTES,
  MAX_SCAN_FILES,
  suggestActionId,
  type ImportScanResult,
} from './assets/importer.ts'
import type { AnimationMap, PetClip, PetHitbox } from './engine/sprite.ts'

export interface CreationFile {
  /** 浏览器里的文件名（可带相对目录）。 */
  name: string
  size: number
  bytes: Uint8Array
  width: number
  height: number
}

export interface PetCreationPlan {
  name: string
  actions: AnimationMap
  hitboxes: PetHitbox[]
  spriteWidth: number
  spriteHeight: number
  /** 写入角色包的相对路径与字节；已包含自动生成的 pet.json。 */
  entries: { rel: string; bytes: Uint8Array }[]
  warnings: string[]
  errors: string[]
}

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'])

const DEFAULT_HITBOXES: PetHitbox[] = [
  {
    id: 'body',
    name: '身体',
    x: 0.08,
    y: 0.06,
    width: 0.84,
    height: 0.88,
    action: 'interact',
    doubleAction: 'jump_happy',
    enabled: true,
  },
]

function extOf(name: string): string {
  return (name.split('.').pop() || '').toLowerCase()
}

function stemOf(name: string): string {
  return (name.split(/[\\/]/).pop() || name).replace(/\.[^.]+$/, '')
}

function safeRel(name: string): string {
  const base = (name.split(/[\\/]/).pop() || 'image.png').replace(/[<>:"|?*\u0000-\u001f]/g, '_')
  return base.replace(/^\.+/, '') || 'image.png'
}

function uniqueRel(rel: string, used: Set<string>): string {
  const lower = rel.toLowerCase()
  if (!used.has(lower)) {
    used.add(lower)
    return rel
  }
  const dot = rel.lastIndexOf('.')
  const stem = dot >= 0 ? rel.slice(0, dot) : rel
  const ext = dot >= 0 ? rel.slice(dot) : ''
  for (let index = 2; index < 1000; index += 1) {
    const candidate = `${stem}-${index}${ext}`
    if (!used.has(candidate.toLowerCase())) {
      used.add(candidate.toLowerCase())
      return candidate
    }
  }
  return `${stem}-${Date.now().toString(36)}${ext}`
}

function manifestClip(clip: PetClip): Record<string, unknown> | null {
  if (clip.type === 'static') return { source: clip.source }
  if (clip.type === 'frames') {
    return { frames: [...clip.sources], fps: clip.fps, loop: clip.loop }
  }
  if (clip.type === 'spritesheet') {
    return {
      type: 'spritesheet',
      source: clip.source,
      frame_width: clip.frameWidth,
      frame_height: clip.frameHeight,
      frame_count: clip.frameCount,
      fps: clip.fps,
      loop: clip.loop,
      start_frame: clip.startFrame,
      end_frame: clip.endFrame,
    }
  }
  if (clip.type === 'model') {
    return {
      type: 'model',
      source: clip.source,
      model_clip: clip.clip,
      loop: clip.loop,
    }
  }
  return null
}

/** 单张/多张图片 → 角色包条目和动作映射。 */
export function buildPetCreationPlan(input: {
  name?: string
  files: CreationFile[]
}): PetCreationPlan {
  const warnings: string[] = []
  const errors: string[] = []
  const used = new Set<string>()
  const normalized: { rel: string; file: CreationFile }[] = []

  if (input.files.length === 0) {
    return {
      name: input.name?.trim() || '新桌宠',
      actions: {},
      hitboxes: DEFAULT_HITBOXES.map(item => ({ ...item })),
      spriteWidth: 128,
      spriteHeight: 160,
      entries: [],
      warnings,
      errors: ['请先选择至少一张图片'],
    }
  }
  if (input.files.length > MAX_SCAN_FILES) {
    errors.push(`文件数 ${input.files.length} 超过上限 ${MAX_SCAN_FILES}`)
  }
  let totalBytes = 0
  for (const file of input.files) {
    const ext = extOf(file.name)
    if (!IMAGE_EXTS.has(ext)) {
      warnings.push(`不支持的文件类型，已跳过：${file.name}`)
      continue
    }
    if (file.size > MAX_ASSET_BYTES) {
      errors.push(`${file.name} 超过单文件上限`)
      continue
    }
    if (file.width <= 0 || file.height <= 0) {
      errors.push(`${file.name} 无法读取图片尺寸`)
      continue
    }
    if (file.width > MAX_IMAGE_EDGE || file.height > MAX_IMAGE_EDGE) {
      errors.push(`${file.name} 尺寸 ${file.width}×${file.height} 超过 ${MAX_IMAGE_EDGE}×${MAX_IMAGE_EDGE}`)
      continue
    }
    totalBytes += file.size
    if (totalBytes > MAX_SCAN_BYTES) {
      errors.push('图片总大小超过角色包上限')
      break
    }
    normalized.push({ rel: uniqueRel(safeRel(file.name), used), file })
  }
  if (normalized.length === 0) {
    return {
      name: input.name?.trim() || '新桌宠',
      actions: {},
      hitboxes: DEFAULT_HITBOXES.map(item => ({ ...item })),
      spriteWidth: 128,
      spriteHeight: 160,
      entries: [],
      warnings,
      errors: errors.length > 0 ? errors : ['没有可用图片'],
    }
  }

  const name = input.name?.trim() || stemOf(normalized[0].rel) || '新桌宠'
  const scan: ImportScanResult = {
    root: name,
    files: normalized.map(item => ({
      rel: item.rel,
      size: item.file.size,
      ext: extOf(item.rel),
    })),
    totalBytes,
  }
  const analysis = analyzeImport(scan, null, name)
  errors.push(...analysis.errors)
  warnings.push(...analysis.warnings)
  const actions: AnimationMap = { ...analysis.actions }

  // analyzeImport 会把 2 张以上同前缀图片识别成序列帧；单张 walk.png 这类
  // 文件不会被序列识别，这里再按动作别名补一次静态映射。
  // 序列帧/图集已经占用的图片不再单独映射成静态动作；单张静态图允许
  // 同时作为 idle 和它自己的动作（例如 walk.png 既是待机兜底也是行走）。
  const usedSources = new Set(
    Object.values(actions).flatMap(clip => {
      if (!clip) return []
      if (clip.type === 'frames') return clip.sources
      if (clip.type === 'spritesheet' || clip.type === 'model') return [clip.source]
      return []
    }),
  )
  for (const item of normalized) {
    if (usedSources.has(item.rel)) continue
    const suggestion = suggestActionId(stemOf(item.rel))
    if (!suggestion || actions[suggestion.actionId]) continue
    actions[suggestion.actionId] = { type: 'static', source: item.rel }
    usedSources.add(item.rel)
  }

  if (!actions.idle && normalized[0]) {
    actions.idle = { type: 'static', source: normalized[0].rel }
    warnings.push('没有识别到待机动作，已把第一张图片作为待机')
  }

  const spriteWidth = Math.max(...normalized.map(item => item.file.width))
  const spriteHeight = Math.max(...normalized.map(item => item.file.height))
  const manifestActions: Record<string, unknown> = {}
  for (const [actionId, clip] of Object.entries(actions)) {
    if (!clip) continue
    const value = manifestClip(clip)
    if (value) manifestActions[actionId] = value
  }
  const manifest = {
    schema_version: 1,
    name,
    hitboxes: DEFAULT_HITBOXES,
    actions: manifestActions,
  }
  const entries = [
    ...normalized.map(item => ({ rel: item.rel, bytes: item.file.bytes })),
    {
      rel: 'pet.json',
      bytes: new TextEncoder().encode(JSON.stringify(manifest, null, 2)),
    },
  ]
  return {
    name,
    actions,
    hitboxes: DEFAULT_HITBOXES.map(item => ({ ...item })),
    spriteWidth,
    spriteHeight,
    entries,
    warnings,
    errors,
  }
}
