/**
 * 角色包解析：`pet.json` 校验、格式识别、动作名自动建议、缺资源回退。
 *
 * user:“角色资源最低要求、缺失依赖和不支持格式均有清晰错误信息，单一资源失败
 * 不导致整个应用崩溃”+“同一角色支持不同 Action 引用不同动画来源/格式”+
 * (只描述资源，不执行任何脚本；不认识的格式明确列入 unsupported，不谎称兼容。)
 */
import { clipPrimarySource, type AnimationMap, type PetClip, type PetHitbox } from '../engine/sprite.ts'
import type { PetRecordConfig } from '../config.ts'

export interface ImportFileInfo {
  rel: string
  size: number
  ext: string
}

export interface ImportScanResult {
  root: string
  files: ImportFileInfo[]
  totalBytes: number
}

export interface PetManifestAction {
  source?: string
  type?: 'static' | 'frames' | 'spritesheet' | 'model'
  clip?: string
  fps?: number
  loop?: boolean
  frame_width?: number
  frame_height?: number
  frame_count?: number
  frames?: string[]
  /** 可选帧范围。 */
  start_frame?: number
  end_frame?: number
  /** 3D 模型的动画片段名与朝向修正。 */
  model_clip?: string
  rotation_y?: number
  model_scale?: number
  offset_y?: number
}

export interface PetManifestV1 {
  schema_version: 1
  name: string
  base_asset?: string
  preview?: string
  scale?: number
  facing?: 1 | -1
  collider?: 'auto' | { radius?: number; width?: number; height?: number }
  actions?: Record<string, PetManifestAction>
  fallbacks?: Record<string, string>
  physics?: Record<string, unknown>
  hitboxes?: PetHitbox[]
  author?: string
  license?: string
}

export interface ImportAnalysis {
  ok: boolean
  name: string
  manifest: PetManifestV1
  actions: AnimationMap
  warnings: string[]
  errors: string[]
  /** 发现了但当前不支持的格式/资源。 */
  unsupported: string[]
  previewSource: string | null
  files: ImportFileInfo[]
  root: string
  /** 自动建议的动作映射（含来源文件名），供预览器里人工修正。 */
  suggestions: { actionId: string; source: string; confidence: number }[]
}

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'])
const MODEL_EXTS = new Set(['glb', 'gltf', 'vrm'])
/** 认识但当前没有可用运行时的格式：明确报出来，不伪装。 */
const UNSUPPORTED_MODEL_EXTS = new Set(['fbx', 'vmd'])
const ANIMATION_EXTS = new Set(['vrma', 'inp', 'inp2d', 'skel', 'atlas', 'plist'])

/** 外部命名 → Sunday 动作 id 的别名表。外部动画不必遵守 Sunday 命名。 */
const ACTION_ALIASES: Record<string, string[]> = {
  idle: ['idle', 'stand', 'default', 'still', '待机'],
  walk: ['walk', 'run', 'move', 'go', '走', '行走'],
  jump: ['jump', 'hop', 'jump_up', '跳'],
  jump_happy: ['jump_happy', 'happyjump', 'joy_jump', 'happy_jump', '开心跳'],
  climb: ['climb', 'climbup', 'climb_up', 'climb_a', '爬'],
  hang: ['hang', 'dangle', 'swing', '挂'],
  fall: ['fall', 'drop', 'falling', '掉'],
  dance: ['dance', 'celebrate', 'cheer', '跳舞'],
  interact: ['interact', 'touch', 'poke', 'click', 'pet', '互动'],
  rest: ['rest', 'sleep', 'sit', 'idle_slow', '休息'],
}

export const BUILTIN_ACTION_IDS = Object.keys(ACTION_ALIASES)

export function suggestActionId(name: string): { actionId: string; confidence: number } | null {
  const normalized = name.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '_')
  for (const [actionId, aliases] of Object.entries(ACTION_ALIASES)) {
    for (const alias of aliases) {
      if (normalized === alias) return { actionId, confidence: 1 }
    }
  }
  for (const [actionId, aliases] of Object.entries(ACTION_ALIASES)) {
    for (const alias of aliases) {
      if (normalized.includes(alias)) return { actionId, confidence: 0.7 }
    }
  }
  return null
}

export function isRelativeSafePath(rel: string): boolean {
  if (!rel || rel.startsWith('/') || rel.startsWith('\\')) return false
  if (/^[a-zA-Z]:/.test(rel)) return false
  const parts = rel.split(/[\\/]/)
  return !parts.some(part => part === '..')
}

export function analyzeImport(scan: ImportScanResult, manifestText?: string | null, nameOverride?: string): ImportAnalysis {
  const warnings: string[] = []
  const errors: string[] = []
  const unsupported: string[] = []
  const files = scan.files.filter(file => isRelativeSafePath(file.rel))
  if (files.length !== scan.files.length) {
    warnings.push('有资源路径不安全（绝对路径或包含 ..），已忽略')
  }
  const byRel = new Map(files.map(file => [file.rel.toLowerCase(), file]))
  for (const file of files) {
    if (UNSUPPORTED_MODEL_EXTS.has(file.ext)) {
      unsupported.push(`${file.rel}（${file.ext.toUpperCase()} 需要专用运行时，当前未接入）`)
    } else if (ANIMATION_EXTS.has(file.ext)) {
      unsupported.push(`${file.rel}（${file.ext.toUpperCase()} 独立骨骼动画文件暂不支持）`)
    }
    else if (file.ext === 'json' && !/pet\.json$/i.test(file.rel)) {
      // 图集元数据按能否解析决定，这里先不报不支持。
    }
  }

  const manifestFile = files.find(file => /^pet\.json$/i.test(file.rel))
    || files.find(file => /(^|\/)pet\.json$/i.test(file.rel))
  const name = (nameOverride || scan.root.split(/[\\/]/).filter(Boolean).pop() || '角色').trim()
  const manifest: PetManifestV1 = manifestFile && manifestText
    ? parseManifest(manifestText, errors, warnings)
    : { schema_version: 1, name }
  if (!manifest.name) manifest.name = name

  const actions: AnimationMap = {}
  const suggestions: { actionId: string; source: string; confidence: number }[] = []

  if (manifest.actions && Object.keys(manifest.actions).length > 0) {
    for (const [actionId, action] of Object.entries(manifest.actions)) {
      const resolved = resolveManifestAction(action, byRel, warnings, actionId)
      if (resolved) {
        actions[actionId] = resolved
        const source = clipPrimarySource(resolved)
        const suggestion = suggestActionId(actionId)
        suggestions.push({ actionId, source: source || '', confidence: suggestion?.confidence ?? 0.9 })
      }
    }
  }

  if (Object.keys(actions).length === 0) {
    const detected = detectFromFiles(files, byRel, warnings)
    Object.assign(actions, detected.actions)
    suggestions.push(...detected.suggestions)
  }

  if (Object.keys(actions).length === 0 && files.length > 0) {
    errors.push('没有可播放的资源：至少需要一张 PNG/JPG/WEBP，或一个 GLB/glTF 模型')
  }
  if (files.length === 0) errors.push('角色包里没有文件')

  if (!actions.idle && Object.keys(actions).length > 0) {
    // 没有任何 idle 资源时用第一个可用资源当静态待机。
    const first = Object.values(actions)[0]
    if (first) {
      actions.idle = first.type === 'frames'
        ? { type: 'frames', sources: [first.sources[0]], fps: 1, loop: true }
        : first.type === 'spritesheet'
          ? { ...first, frameCount: 1, startFrame: first.startFrame ?? 0, endFrame: first.startFrame ?? 0 }
          : first
      warnings.push('没有 idle 资源，已用第一个可用动作作为待机姿态')
    }
  }

  const preview = resolvePreview(manifest, actions, byRel)
  return {
    ok: errors.length === 0,
    name: manifest.name,
    manifest,
    actions,
    warnings,
    errors,
    unsupported,
    previewSource: preview,
    files,
    root: scan.root,
    suggestions,
  }
}

function parseManifest(text: string, errors: string[], warnings: string[]): PetManifestV1 {
  try {
    const parsed = JSON.parse(text) as PetManifestV1
    if (typeof parsed !== 'object' || parsed === null) throw new Error('不是对象')
    if (parsed.schema_version !== 1) {
      warnings.push(`pet.json 的 schema_version 为 ${String(parsed.schema_version)}，按 v1 解析`)
    }
    return { ...parsed, schema_version: 1, name: String(parsed.name || '') }
  } catch (error) {
    errors.push(`pet.json 解析失败：${error instanceof Error ? error.message : String(error)}`)
    return { schema_version: 1, name: '' }
  }
}

function resolveManifestAction(
  action: PetManifestAction,
  byRel: Map<string, ImportFileInfo>,
  warnings: string[],
  actionId: string,
): PetClip | null {
  const type = action.type || (action.frames?.length ? 'frames' : action.frame_count ? 'spritesheet' : 'static')
  if (type === 'model') {
    if (!action.source || !byRel.has(action.source.toLowerCase())) {
      warnings.push(`${actionId}：模型文件不存在（${action.source || '未指定'}）`)
      return null
    }
    const ext = action.source.split('.').pop()?.toLowerCase() || ''
    if (ext !== 'glb' && ext !== 'gltf' && ext !== 'vrm') {
      warnings.push(`${actionId}：${ext.toUpperCase()} 模型暂不支持，已跳过`)
      return null
    }
    return {
      type: 'model',
      source: action.source,
      clip: action.model_clip || action.clip,
      loop: action.loop !== false,
      rotationY: action.rotation_y,
      modelScale: action.model_scale,
      offsetY: action.offset_y,
    }
  }
  if (type === 'frames' || action.frames?.length) {
    const sources = (action.frames || (action.source ? [action.source] : [])).filter(Boolean)
    const available = sources.filter(source => byRel.has(source.toLowerCase()))
    if (available.length === 0) {
      warnings.push(`${actionId}：帧图不存在（${sources.join(', ') || '未指定'}）`)
      return null
    }
    if (available.length !== sources.length) warnings.push(`${actionId}：缺少 ${sources.length - available.length} 张帧图`)
    return { type: 'frames', sources: available, fps: action.fps ?? 12, loop: action.loop !== false }
  }
  if (type === 'spritesheet') {
    if (!action.source || !byRel.has(action.source.toLowerCase())) {
      warnings.push(`${actionId}：图集文件不存在（${action.source || '未指定'}）`)
      return null
    }
    return {
      type: 'spritesheet',
      source: action.source,
      frameWidth: Math.max(1, action.frame_width || 0),
      frameHeight: Math.max(1, action.frame_height || 0),
      frameCount: Math.max(1, action.frame_count || 1),
      fps: action.fps ?? 12,
      loop: action.loop !== false,
      startFrame: action.start_frame,
      endFrame: action.end_frame,
    }
  }
  if (!action.source || !byRel.has(action.source.toLowerCase())) {
    warnings.push(`${actionId}：图片不存在（${action.source || '未指定'}）`)
    return null
  }
  return { type: 'static', source: action.source }
}

function detectFromFiles(
  files: ImportFileInfo[],
  byRel: Map<string, ImportFileInfo>,
  warnings: string[],
): { actions: AnimationMap; suggestions: { actionId: string; source: string; confidence: number }[] } {
  const actions: AnimationMap = {}
  const suggestions: { actionId: string; source: string; confidence: number }[] = []
  const images = files.filter(file => IMAGE_EXTS.has(file.ext))
  if (images.length === 0) {
    // 没有图片时先看模型：GLB/glTF 单独存在也算一个可用角色。
    const model = files.find(file => MODEL_EXTS.has(file.ext))
    if (model) {
      actions.idle = { type: 'model', source: model.rel, loop: true }
      suggestions.push({ actionId: 'idle', source: model.rel, confidence: 0.8 })
    }
    return { actions, suggestions }
  }

  // 1) 图集元数据：Aseprite / TexturePacker 的 frames 数组。
  const atlasJson = files.find(file => file.ext === 'json' && !/pet\.json$/i.test(file.rel))
  const sequences = new Map<string, ImportFileInfo[]>()
  for (const file of images) {
    const match = file.rel.match(/^(.*?)[-_ ]?(\d{1,4})\.(png|jpg|jpeg|webp|bmp)$/i)
    if (match) {
      const key = match[1].toLowerCase()
      const list = sequences.get(key) || []
      list.push(file)
      sequences.set(key, list)
    }
  }
  for (const [key, list] of sequences) {
    if (list.length < 2) continue
    list.sort((a, b) => {
      const na = Number(a.rel.match(/(\d{1,4})\./)?.[1] || 0)
      const nb = Number(b.rel.match(/(\d{1,4})\./)?.[1] || 0)
      return na - nb
    })
    const label = key.split('/').pop() || key
    const suggestion = suggestActionId(label) || { actionId: 'idle', confidence: 0.4 }
    if (actions[suggestion.actionId]) continue
    actions[suggestion.actionId] = {
      type: 'frames',
      sources: list.map(file => file.rel),
      fps: 12,
      loop: suggestion.actionId !== 'jump' && suggestion.actionId !== 'jump_happy',
    }
    suggestions.push({ actionId: suggestion.actionId, source: list[0].rel, confidence: suggestion.confidence })
  }

  if (Object.keys(actions).length === 0) {
    // 2) 没有图片但有 GLB/glTF：直接用模型当基础姿态。
    const model = files.find(file => MODEL_EXTS.has(file.ext) && !/\.bin$/i.test(file.rel))
    if (model) {
      actions.idle = { type: 'model', source: model.rel, loop: true }
      suggestions.push({ actionId: 'idle', source: model.rel, confidence: 0.8 })
      return { actions, suggestions }
    }
    // 3) 单图：最大的那张当基础姿态。
    const sorted = [...images].sort((a, b) => b.size - a.size)
    const base = sorted[0]
    actions.idle = { type: 'static', source: base.rel }
    suggestions.push({ actionId: 'idle', source: base.rel, confidence: 0.9 })
    if (atlasJson) warnings.push(`${atlasJson.rel} 存在但没有可用的图集描述，按单图处理`)
  }
  return { actions, suggestions }
}

function resolvePreview(manifest: PetManifestV1, actions: AnimationMap, byRel: Map<string, ImportFileInfo>): string | null {
  if (manifest.preview && byRel.has(manifest.preview.toLowerCase())) return manifest.preview
  if (manifest.base_asset && byRel.has(manifest.base_asset.toLowerCase())) return manifest.base_asset
  const idle = actions.idle
  if (!idle) return null
  const source = clipPrimarySource(idle)
  return source || null
}

/**
 * 生成可持久化的角色记录（预览器确认后才写入桌面）。
 */
export function buildPetRecord(
  analysis: ImportAnalysis,
  options: { id: string; packId: string | null; spriteWidth: number; spriteHeight: number; scale?: number },
): PetRecordConfig {
  const radius = Math.max(10, Math.round(Math.min(options.spriteWidth, options.spriteHeight) * 0.38))
  const manifestHitboxes = analysis.manifest.hitboxes
  return {
    id: options.id,
    name: analysis.name,
    packId: options.packId,
    scale: options.scale ?? analysis.manifest.scale ?? 1,
    facing: analysis.manifest.facing === -1 ? -1 : 1,
    radius,
    visible: true,
    actions: analysis.actions,
    spriteWidth: options.spriteWidth,
    spriteHeight: options.spriteHeight,
    hitboxes: Array.isArray(manifestHitboxes) && manifestHitboxes.length > 0
      ? manifestHitboxes
      : [
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
      ],
    physics: (analysis.manifest.physics || {}) as Record<string, number>,
    behavior: {},
    importWarnings: [...analysis.warnings, ...analysis.unsupported],
  }
}
