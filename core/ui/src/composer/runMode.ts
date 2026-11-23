/**
 * 会话运行模式：聊天 / 工作。
 *
 * user:“将现有的consider，excute迭代为 super Agent、chat、work”“新建会话时选择好，
 * 就不可变动了”+(运行模式在新建会话时选定；旧名字读进来归一到新名字，免得老会话
 * 显示出前端不认识的模式)。
 *
 * user:“把智能模式隐藏掉，从下个版本开始，仅聊天和工作模式”+(界面上只提供聊天与工作；
 * `auto` 这个名字不删——旧会话、旧存档、旧 API 调用仍在用它，后端也照旧接受，读到
 * 就按工作处理，同时把存档改写成 work，避免「界面显示工作、实际按智能跑」)。
 */

/** 界面上可选的运行模式：只有聊天与工作。 */
export const CORE_RUN_MODES = ['chat', 'work'] as const

export type CoreRunMode = (typeof CORE_RUN_MODES)[number]

/** 已从界面隐藏、后端仍兼容的模式名；不要拿去渲染入口。 */
export const HIDDEN_RUN_MODES = ['auto'] as const

export const CORE_RUN_MODE_LABELS: Record<CoreRunMode, string> = {
  chat: '聊天',
  work: '工作',
}

export const CORE_RUN_MODE_DESCRIPTIONS: Record<CoreRunMode, string> = {
  chat: '只讨论、查阅和分析，不改任何文件',
  work: '当场把活干完，可以改文件、跑命令',
}

/** 隐藏模式读进来落到哪个可选模式：工作模式能力更完整，历史 auto 会话按它继续。 */
const HIDDEN_RUN_MODE_FALLBACKS: Record<string, CoreRunMode> = {
  auto: 'work',
}

/** 更早的名字：先归一到新名字，再走隐藏模式那一套。 */
const LEGACY_RUN_MODES: Record<string, string> = {
  consider: 'chat',
  execute: 'work',
  superagent: 'auto',
}

export const DEFAULT_RUN_MODE: CoreRunMode = 'work'

/** 旧名字、隐藏模式、空值、未知值一律落到界面认识的两个模式上。 */
export function normalizeCoreRunMode(value: unknown): CoreRunMode {
  const raw = String(value ?? '').trim()
  const aliased = LEGACY_RUN_MODES[raw] || raw
  const hidden = HIDDEN_RUN_MODE_FALLBACKS[aliased]
  if (hidden) return hidden
  return (CORE_RUN_MODES as readonly string[]).includes(aliased)
    ? (aliased as CoreRunMode)
    : DEFAULT_RUN_MODE
}

/**
 * 读到的是不是「已被隐藏的模式」（auto 及其旧名 superagent）。
 *
 * 用来判断存档要不要迁移：只有隐藏模式必须改写成 work，其余未知值继续按默认处理，
 * 不去改动用户的存档。
 */
export function isHiddenCoreRunMode(value: unknown): boolean {
  const raw = String(value ?? '').trim()
  const aliased = LEGACY_RUN_MODES[raw] || raw
  return (HIDDEN_RUN_MODES as readonly string[]).includes(aliased)
}

export function isCoreRunModeFixed(value: unknown): boolean {
  const raw = String(value ?? '').trim()
  return raw.length > 0
}
