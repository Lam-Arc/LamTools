/**
 * 桌宠配置：带版本号、可迁移、可持久化。
 *
 * user:“用户配置与默认值具有明确版本号，可从旧版迁移/初始化”+
 * (所有默认值集中在这里，写进技术文档，不在交互语义上偷偷改。
 *  桌宠右键临时会话切换明确不落盘。)
 */
import type { BehaviorConfig } from './engine/behavior.ts'
import type { PhysicsConfig } from './engine/physics.ts'
import type { PetHitbox } from './engine/sprite.ts'
import type { TerrainQuality } from './engine/terrain.ts'
import type { PetBindingsState } from './agent/host.ts'
import type { AnimationMap } from './engine/sprite.ts'

export const PET_CONFIG_VERSION = 1

export type PingSectorKind = 'question' | 'exclamation' | 'note' | 'select' | 'chat' | 'switch' | 'custom' | 'subring'

export interface PingSectorConfig {
  id: string
  label: string
  /** 图标字符（用户可改）。 */
  icon: string
  kind: PingSectorKind
  color: string
  /** 固定提示词模板，?、!、记录 各自独立可编辑。 */
  prompt?: string
  /** custom 项绑定的动作（打开设置、隐藏桌宠等）。 */
  action?: string
  /** 子轮盘 id（kind=subring）。 */
  subring?: string
  /** 属于哪个子轮盘；没有 group 的项出现在主轮盘。 */
  group?: string
  enabled: boolean
}

export interface PingConfig {
  hotkey: string
  /** 环半径（物理像素）。 */
  radius: number
  /** 环身宽度：细环，中心保持透明。 */
  ringWidth: number
  /** 中心盘（内环）半径；不填时按外径的 42% 自动算。 */
  hubRadius?: number
  /** 环的背景图：data URL，支持 PNG/JPEG/WebP/GIF（动图）等。 */
  background?: string
  sectors: PingSectorConfig[]
  autoAttachScreenshot: boolean
  /** 标记动画时长，2–3 秒区间。 */
  markerMs: number
  target: { projectId: string | null; sessionId: string | null }
}

export type BubblePolicy = 'popup' | 'badge' | 'silent'

export interface BubbleConfig {
  question: BubblePolicy
  approval: BubblePolicy
  reply: BubblePolicy
  done: BubblePolicy
  /** 默认只展开一个；用户可主动展开多个。 */
  maxExpanded: number
}

export interface PetRecordConfig {
  id: string
  name: string
  packId: string | null
  scale: number
  facing: 1 | -1
  radius: number
  visible: boolean
  /** 动作 → 资源引用（相对角色包根）。 */
  actions: AnimationMap
  spriteWidth: number
  spriteHeight: number
  hitboxes: PetHitbox[]
  physics: Partial<PhysicsConfig>
  behavior: Partial<BehaviorConfig>
  importWarnings: string[]
}

export interface PetConfigV1 {
  version: number
  enabled: boolean
  quality: TerrainQuality
  useL3: boolean
  /** top 置顶；behind 压到窗口之下；clip 置顶但按真实窗口几何裁掉宠物。 */
  zMode: 'top' | 'behind' | 'clip'
  debugOverlay: {
    terrain: boolean
    colliders: boolean
    path: boolean
    velocity: boolean
  }
  ping: PingConfig
  bubbles: BubbleConfig
  pets: PetRecordConfig[]
  /** 内置方块人预设是否已经装过一次；用户删掉后不再自动加回来。 */
  presetInstalled: boolean
  bindings: PetBindingsState
  perf: {
    /** 渲染上限帧率。 */
    maxFps: number
    /** 空闲时降低 L3 识别频率。 */
    idleQuality: boolean
    /** L3 刷新周期（毫秒）。 */
    l3RefreshMs: number
  }
}

// user:“提问就是发一个图和“？”，注意就是发一个“！”，记录就是发一个图和“记录”，
// 不要带那么多有的没的”+(发送文字就是扇区符号本身，不再拼长提示词。)
export const DEFAULT_PING_PROMPTS = {
  question: '？',
  exclamation: '！',
  note: '记录',
}

export function defaultPingSectors(): PingSectorConfig[] {
  return [
    { id: 'question', label: '提问', icon: '?', kind: 'question', color: '#6AA8FF', prompt: DEFAULT_PING_PROMPTS.question, enabled: true },
    { id: 'exclamation', label: '注意', icon: '!', kind: 'exclamation', color: '#FF9F5A', prompt: DEFAULT_PING_PROMPTS.exclamation, enabled: true },
    { id: 'note', label: '记录', icon: '记', kind: 'note', color: '#7ED6A5', prompt: DEFAULT_PING_PROMPTS.note, enabled: true },
    { id: 'select', label: '框选', icon: '框', kind: 'select', color: '#C7A6FF', enabled: true },
    { id: 'chat', label: '对话', icon: '聊', kind: 'chat', color: '#8FD6FF', enabled: true },
    { id: 'switch', label: '切换会话', icon: '⇄', kind: 'switch', color: '#BFC7D5', enabled: true },
  ]
}

export function defaultConfig(): PetConfigV1 {
  return {
    version: PET_CONFIG_VERSION,
    enabled: true,
    quality: 'balanced',
    // user:"默认关闭啦 l3"+(L3 视觉边缘识别默认关闭：不抓屏、不建视觉地形；
    // 需要时在设置里手动打开。)
    useL3: false,
    zMode: 'top',
    debugOverlay: { terrain: false, colliders: false, path: false, velocity: false },
    ping: {
      hotkey: 'Ctrl+Alt+Space',
      radius: 132,
      ringWidth: 14,
      sectors: defaultPingSectors(),
      autoAttachScreenshot: true,
      markerMs: 2400,
      target: { projectId: null, sessionId: null },
    },
    bubbles: {
      question: 'popup',
      approval: 'popup',
      reply: 'badge',
      done: 'badge',
      maxExpanded: 1,
    },
    pets: [],
    presetInstalled: false,
    bindings: { pets: {}, ping: { projectId: null, sessionId: null } },
    perf: { maxFps: 60, idleQuality: true, l3RefreshMs: 30_000 },
  }
}

export interface MigrationResult {
  config: PetConfigV1
  migratedFrom: number | null
  warnings: string[]
}

/**
 * 迁移入口：未知字段保留默认值，缺字段补默认值，版本号向上兼容。
 * 旧版（无 version）按 0 处理，尽量搬运能认识的字段。
 */
export function migrateConfig(raw: unknown): MigrationResult {
  const warnings: string[] = []
  const base = defaultConfig()
  if (!raw || typeof raw !== 'object') {
    return { config: base, migratedFrom: null, warnings: ['配置为空，已写入默认值'] }
  }
  const input = raw as Partial<PetConfigV1> & Record<string, unknown>
  const fromVersion = typeof input.version === 'number' ? input.version : 0
  const config: PetConfigV1 = {
    ...base,
    ...pick(input, ['enabled', 'quality', 'useL3', 'zMode']),
    debugOverlay: { ...base.debugOverlay, ...(input.debugOverlay || {}) },
    ping: {
      ...base.ping,
      ...(input.ping || {}),
      // 提示词模板永远补齐，旧配置里没有的用默认模板。
      sectors: mergeSectors(base.ping.sectors, input.ping?.sectors),
      target: { ...base.ping.target, ...(input.ping?.target || {}) },
    },
    bubbles: { ...base.bubbles, ...(input.bubbles || {}) },
    pets: Array.isArray(input.pets) ? input.pets.map(normalizePetRecord).filter(Boolean) as PetRecordConfig[] : [],
    presetInstalled: input.presetInstalled === true,
    bindings: {
      pets: { ...(input.bindings?.pets || {}) },
      ping: { ...base.bindings.ping, ...(input.bindings?.ping || {}) },
    },
    perf: { ...base.perf, ...(input.perf || {}) },
    version: PET_CONFIG_VERSION,
  }
  if (fromVersion < PET_CONFIG_VERSION) {
    warnings.push(`配置从 v${fromVersion} 迁移到 v${PET_CONFIG_VERSION}`)
  }
  return { config, migratedFrom: fromVersion < PET_CONFIG_VERSION ? fromVersion : null, warnings }
}

function pick<T extends object>(source: T, keys: (keyof PetConfigV1)[]): Partial<PetConfigV1> {
  const output: Record<string, unknown> = {}
  for (const key of keys) {
    if ((source as Record<string, unknown>)[key as string] !== undefined) {
      output[key as string] = (source as Record<string, unknown>)[key as string]
    }
  }
  return output as Partial<PetConfigV1>
}

// 旧版默认提示词：配置里存过这些原文的，迁移时换成新的短提示；
// 用户自己改过的提示词保持不动。
const LEGACY_PING_PROMPTS: Partial<Record<PingSectorKind, string[]>> = {
  question: [
    '看这张截图里我标出来的位置（标记坐标已写在图上）：这是什么、它在做什么、我需要关心什么？请结合画面给结论。',
  ],
  exclamation: [
    '看这张截图里我标出来的位置：有没有异常、风险或与预期不符的地方？说明你的判断依据和需要我处理的事项。',
  ],
  note: [
    '把这张截图里的信息整理成要点记录下来（不要写本地文件，直接在会话里给我）：分主题列关键事实、数字和待办。',
  ],
}

function mergeSectors(defaults: PingSectorConfig[], incoming: PingSectorConfig[] | undefined): PingSectorConfig[] {
  if (!Array.isArray(incoming) || incoming.length === 0) return defaults
  // 用户自定义项优先保留；默认项缺提示词时补上模板。
  return incoming.map(sector => {
    const fallback = defaults.find(item => item.id === sector.id)
    const legacy = LEGACY_PING_PROMPTS[sector.kind] || []
    const prompt = sector.prompt && !legacy.includes(sector.prompt)
      ? sector.prompt
      : fallback?.prompt
    return {
      ...fallback,
      ...sector,
      prompt,
    } as PingSectorConfig
  })
}

/**
 * 动作片段归一化。
 *
 * 设计文档的 frames 片段写 `frames: [...]`（pet.json 也是），内部统一成
 * `sources`；老导入路径把 pet.json 原样塞进配置时，`frameAt` 读 `sources`
 * 会抛 "Cannot read properties of undefined"，整个渲染循环每帧崩掉、桌宠消失。
 */
function normalizeActions(raw: unknown): AnimationMap {
  const map: AnimationMap = {}
  if (!raw || typeof raw !== 'object') return map
  for (const [actionId, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!value || typeof value !== 'object') continue
    const clip = { ...(value as Record<string, unknown>) }
    if (clip.type === 'frames' && !Array.isArray(clip.sources) && Array.isArray(clip.frames)) {
      clip.sources = clip.frames
    }
    map[actionId] = clip as never
  }
  return map
}

function normalizePetRecord(raw: unknown): PetRecordConfig | null {
  if (!raw || typeof raw !== 'object') return null
  const input = raw as Partial<PetRecordConfig>
  if (!input.id) return null
  return {
    id: String(input.id),
    name: String(input.name || input.id),
    packId: input.packId ? String(input.packId) : null,
    scale: clampNumber(input.scale, 0.1, 8, 1),
    facing: input.facing === -1 ? -1 : 1,
    radius: clampNumber(input.radius, 4, 256, 26),
    visible: input.visible !== false,
    actions: normalizeActions(input.actions),
    spriteWidth: clampNumber(input.spriteWidth, 8, 4096, 128),
    spriteHeight: clampNumber(input.spriteHeight, 8, 4096, 160),
    hitboxes: Array.isArray(input.hitboxes) ? input.hitboxes : [],
    physics: input.physics || {},
    behavior: input.behavior || {},
    importWarnings: Array.isArray(input.importWarnings) ? input.importWarnings : [],
  }
}

function clampNumber(value: unknown, min: number, max: number, fallback: number): number {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  return Math.min(max, Math.max(min, number))
}

export function parseConfigText(text: string): MigrationResult {
  try {
    return migrateConfig(JSON.parse(text))
  } catch (error) {
    return {
      config: defaultConfig(),
      migratedFrom: null,
      warnings: [`配置文件无法解析（${error instanceof Error ? error.message : String(error)}），已用默认值`],
    }
  }
}
