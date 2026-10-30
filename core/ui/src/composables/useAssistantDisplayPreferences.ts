import { readonly, reactive } from 'vue'

/**
 * Assistant 显示偏好（气泡 / 自动拆分 / 名称 / 头像）。
 *
 * user:“Assistant 可选择是否使用消息气泡”“支持自定义 Assistant 显示名称和头像”
 * “支持开启或关闭自动气泡拆分”+(这三项都只是展示偏好，存进现有偏好存储，
 * 不新建存储体系，也不进入消息协议)。
 *
 * 说明：读侧（MessageView）与写侧（设置面板）必须共享同一份状态，所以这里做成
 * 模块级单例；持久化沿用既有的 localStorage 偏好键 + `settings.update`
 * （core.* 命名空间）双写，和 useCoreUpdateState 等现有偏好同一套机制。
 */
export interface AssistantDisplayPreferences {
  /** 回复是否套气泡（关闭时保持原来的无边框正文） */
  bubblesEnabled: boolean
  /** 是否按结构规则自动拆分（模型标记始终生效） */
  splitEnabled: boolean
  /** 自定义显示名称，空串表示用默认名 */
  name: string
  /** 自定义头像（图片地址或 data URL），空串表示用名称首字母 */
  avatar: string
  // user:“头上头像显示大小太小了 设成可调节，裁切也是圆角率可调节”+
  // (头像在消息头左侧的显示尺寸与圆角率都做成可调偏好，默认值加粗到 28px)
  /** 头像显示边长（px） */
  avatarSize: number
  /** 圆角率 0–100：100 为圆形，0 为方形 */
  avatarRoundness: number
}

/** 与其它本地偏好的键名风格一致（lamtools.core.*）。 */
export const ASSISTANT_DISPLAY_STORAGE_KEY = 'lamtools.core.assistantDisplay'
/** 设置面板持久化用的既有设置命名空间（settings.get / settings.update）。 */
export const ASSISTANT_DISPLAY_NAMESPACE = 'core.assistantDisplay'

export const ASSISTANT_DISPLAY_DEFAULTS: AssistantDisplayPreferences = {
  bubblesEnabled: false,
  splitEnabled: false,
  name: '',
  avatar: '',
  avatarSize: 28,
  avatarRoundness: 100,
}

export const AVATAR_SIZE_MIN = 16
export const AVATAR_SIZE_MAX = 72
export const AVATAR_ROUNDNESS_MIN = 0
export const AVATAR_ROUNDNESS_MAX = 100

const MAX_NAME_LENGTH = 40
// user:“助手头像那块别填链接 上传，裁切”+(裁切结果是 256px 正方形的 data URL，
// 旧上限 4096 只够放链接；这里放宽到能装下图片本身，同时避免异常超长值写进设置文件)
const MAX_AVATAR_LENGTH = 400_000

const state = reactive<AssistantDisplayPreferences>({ ...ASSISTANT_DISPLAY_DEFAULTS })

/** 只读句柄：渲染侧不会误写状态。 */
export const assistantDisplayPreferences = readonly(state)

function clampText(value: unknown, maxLength: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
}

function clampNumber(value: unknown, min: number, max: number): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  return Math.min(max, Math.max(min, Math.round(value)))
}

export function normalizeAssistantDisplayPreferences(value: unknown): Partial<AssistantDisplayPreferences> {
  if (!value || typeof value !== 'object') return {}
  const raw = value as Record<string, unknown>
  const next: Partial<AssistantDisplayPreferences> = {}
  if (typeof raw.bubblesEnabled === 'boolean') next.bubblesEnabled = raw.bubblesEnabled
  if (typeof raw.splitEnabled === 'boolean') next.splitEnabled = raw.splitEnabled
  if (typeof raw.name === 'string') next.name = clampText(raw.name, MAX_NAME_LENGTH)
  if (typeof raw.avatar === 'string') next.avatar = clampText(raw.avatar, MAX_AVATAR_LENGTH)
  const size = clampNumber(raw.avatarSize, AVATAR_SIZE_MIN, AVATAR_SIZE_MAX)
  if (size !== undefined) next.avatarSize = size
  const roundness = clampNumber(raw.avatarRoundness, AVATAR_ROUNDNESS_MIN, AVATAR_ROUNDNESS_MAX)
  if (roundness !== undefined) next.avatarRoundness = roundness
  return next
}

function readStored(): Partial<AssistantDisplayPreferences> {
  if (typeof window === 'undefined' || !window.localStorage) return {}
  try {
    return normalizeAssistantDisplayPreferences(JSON.parse(window.localStorage.getItem(ASSISTANT_DISPLAY_STORAGE_KEY) || 'null'))
  } catch {
    return {}
  }
}

function writeStored(snapshot: AssistantDisplayPreferences): void {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    window.localStorage.setItem(ASSISTANT_DISPLAY_STORAGE_KEY, JSON.stringify(snapshot))
  } catch {
    /* 隐私模式 / 配额受限：持久化尽力而为，界面状态照常生效 */
  }
}

export function assistantDisplaySnapshot(): AssistantDisplayPreferences {
  return { ...state }
}

/** 写入偏好：更新内存状态并落到本地偏好键。 */
export function setAssistantDisplayPreferences(patch: Partial<AssistantDisplayPreferences>): AssistantDisplayPreferences {
  const next = normalizeAssistantDisplayPreferences({ ...state, ...patch })
  if (typeof next.bubblesEnabled === 'boolean') state.bubblesEnabled = next.bubblesEnabled
  if (typeof next.splitEnabled === 'boolean') state.splitEnabled = next.splitEnabled
  if (typeof next.name === 'string') state.name = next.name
  if (typeof next.avatar === 'string') state.avatar = next.avatar
  if (typeof next.avatarSize === 'number') state.avatarSize = next.avatarSize
  if (typeof next.avatarRoundness === 'number') state.avatarRoundness = next.avatarRoundness
  const snapshot = assistantDisplaySnapshot()
  writeStored(snapshot)
  return snapshot
}

/** 启动时同步一次本地偏好（模块加载即执行，首帧渲染就能拿到正确值）。 */
export function loadAssistantDisplayPreferences(): void {
  const stored = readStored()
  if (Object.keys(stored).length > 0) setAssistantDisplayPreferences(stored)
}

loadAssistantDisplayPreferences()
